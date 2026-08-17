<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onDestroy, onMount } from 'svelte';

	import {
		cancelCatalogJob,
		enqueueCatalogTrack,
		getCatalogBatchStatus,
		normalizeCatalogJob,
		retryCatalogJob
	} from '$lib/services/catalogApi.js';
	import { ApiError } from '$lib/services/api.js';
	import { onUserEvent } from '$lib/services/realtimeSocket.js';
	import { authStore } from '$lib/stores/authStore.js';

	const ACCEPTED_TYPES = 'audio/mpeg,audio/wav,audio/ogg,audio/flac';
	const ACCEPTED_COVER_TYPES = 'image/jpeg,image/png,image/webp';
	// Reconnect-and-restore (requirement 6): the *only* client-side state that
	// survives a refresh/navigation is this id -- everything else (per-file
	// progress, which files are done) lives durably server-side in Redis and
	// is re-fetched from there on mount, never reconstructed from memory.
	const BATCH_STORAGE_KEY = 'cuemix:upload:activeBatchId';
	// Realtime (WebSocket) status pushes are primary; this is only a slow
	// safety net in case an event is ever missed (e.g. a push landing in the
	// brief window before this page's subscription is established).
	const FALLBACK_POLL_MS = 5000;

	const ACTIVE_STATUSES = new Set(['queued', 'validating', 'storing', 'analyzing']);
	const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);

	/** @typedef {{
	 * key: number,
	 * file: File | null,
	 * cover: File | null,
	 * filename: string,
	 * title: string,
	 * artist: string,
	 * album: string,
	 * genre: string,
	 * lyrics: string,
	 * visibility: 'private' | 'public',
	 * status: 'idle' | 'queued' | 'validating' | 'storing' | 'analyzing' | 'completed' | 'failed' | 'cancelled',
	 * error: string,
	 * jobId: string | null,
	 * locked: boolean,
	 * track: ReturnType<typeof import('$lib/services/catalogApi.js').normalizeCatalogTrack> | null
	 * }} SongCard */

	let nextKey = 1;
	/** @returns {SongCard} */
	function blankCard() {
		return {
			key: nextKey++,
			file: null,
			cover: null,
			filename: '',
			title: '',
			artist: '',
			album: '',
			genre: '',
			lyrics: '',
			visibility: 'public',
			status: 'idle',
			error: '',
			jobId: null,
			locked: false,
			track: null
		};
	}

	/** @type {SongCard[]} */
	let cards = $state([blankCard()]);
	let uploading = $state(false);
	let restoring = $state(false);
	/** @type {string | null} */
	let batchId = $state(null);
	let formError = $state('');
	/** @type {ReturnType<typeof setTimeout> | null} */
	let fallbackPollHandle = null;
	/** @type {(() => void) | null} */
	let unsubscribeLive = null;

	let batchDone = $derived(
		batchId !== null && cards.every((card) => TERMINAL_STATUSES.has(card.status))
	);
	let completedCount = $derived(cards.filter((card) => card.status === 'completed').length);
	let failedCount = $derived(cards.filter((card) => card.status === 'failed').length);
	let cancelledCount = $derived(cards.filter((card) => card.status === 'cancelled').length);
	let settledCount = $derived(completedCount + failedCount + cancelledCount);
	let overallPercent = $derived(cards.length ? Math.round((settledCount / cards.length) * 100) : 0);

	$effect(() => {
		if ($authStore.status === 'guest') {
			void goto(resolve('/login'));
		}
	});

	onMount(() => {
		const savedBatchId =
			typeof localStorage !== 'undefined' ? localStorage.getItem(BATCH_STORAGE_KEY) : null;
		if (savedBatchId) void restoreBatch(savedBatchId);
	});

	onDestroy(() => {
		stopFallbackPolling();
		unsubscribeLive?.();
	});

	/** @param {string} id */
	function persistBatchId(id) {
		batchId = id;
		if (typeof localStorage !== 'undefined') localStorage.setItem(BATCH_STORAGE_KEY, id);
	}

	function clearPersistedBatch() {
		batchId = null;
		if (typeof localStorage !== 'undefined') localStorage.removeItem(BATCH_STORAGE_KEY);
	}

	function stopFallbackPolling() {
		if (fallbackPollHandle) {
			clearTimeout(fallbackPollHandle);
			fallbackPollHandle = null;
		}
	}

	/** @param {ReturnType<typeof normalizeCatalogJob>} job */
	function applyJobUpdate(job) {
		cards = cards.map((card) =>
			card.jobId === job.jobId
				? {
						...card,
						status: /** @type {SongCard['status']} */ (job.status),
						error: job.error || '',
						track: job.track || card.track,
						title: job.track?.title || card.title,
						artist: job.track?.artist || card.artist,
						album: job.track?.album || card.album
					}
				: card
		);
	}

	/** @param {string} activeBatchId */
	async function refreshBatch(activeBatchId) {
		try {
			const status = await getCatalogBatchStatus(activeBatchId);
			for (const job of status.jobs) applyJobUpdate(job);
		} catch {
			// Best-effort resync; the live subscription and the next fallback
			// tick will both retry.
		}
	}

	/** @param {string} activeBatchId */
	function subscribeLive(activeBatchId) {
		unsubscribeLive?.();
		unsubscribeLive = onUserEvent(
			(type, data) => {
				if (type !== 'catalog_job_updated') return;
				const job = normalizeCatalogJob(data);
				if (job.batchId !== activeBatchId) return;
				applyJobUpdate(job);
			},
			{ onResync: () => void refreshBatch(activeBatchId) }
		);
	}

	/** @param {string} activeBatchId */
	function scheduleFallbackPoll(activeBatchId) {
		stopFallbackPolling();
		if (batchId !== activeBatchId) return;
		if (cards.every((card) => TERMINAL_STATUSES.has(card.status))) {
			uploading = false;
			return;
		}
		fallbackPollHandle = setTimeout(async () => {
			await refreshBatch(activeBatchId);
			scheduleFallbackPoll(activeBatchId);
		}, FALLBACK_POLL_MS);
	}

	/** @param {string} savedBatchId */
	async function restoreBatch(savedBatchId) {
		restoring = true;
		try {
			const status = await getCatalogBatchStatus(savedBatchId);
			if (!status.jobs.length) {
				clearPersistedBatch();
				return;
			}
			persistBatchId(savedBatchId);
			cards = status.jobs.map((job) => ({
				...blankCard(),
				filename: job.filename,
				title: job.track?.title || '',
				artist: job.track?.artist || '',
				album: job.track?.album || '',
				status: /** @type {SongCard['status']} */ (job.status),
				error: job.error || '',
				jobId: job.jobId,
				locked: true,
				track: job.track
			}));
			subscribeLive(savedBatchId);
			if (cards.some((card) => ACTIVE_STATUSES.has(card.status))) {
				uploading = true;
				scheduleFallbackPoll(savedBatchId);
			}
		} catch (restoreError) {
			if (restoreError instanceof ApiError && restoreError.status === 404) {
				clearPersistedBatch();
			}
		} finally {
			restoring = false;
		}
	}

	function addCard() {
		cards = [...cards, blankCard()];
	}

	/** @param {number} key */
	function removeCard(key) {
		if (cards.length <= 1) return;
		cards = cards.filter((card) => card.key !== key);
	}

	/** @param {number} key @param {Event} event */
	function selectFile(key, event) {
		const input = /** @type {HTMLInputElement} */ (event.currentTarget);
		const file = input.files?.[0] || null;
		cards = cards.map((card) => (card.key === key ? { ...card, file, error: '' } : card));
	}

	/** @param {number} key @param {Event} event */
	function selectCover(key, event) {
		const input = /** @type {HTMLInputElement} */ (event.currentTarget);
		const cover = input.files?.[0] || null;
		cards = cards.map((card) => (card.key === key ? { ...card, cover } : card));
	}

	/** @param {SongCard} card */
	function cardValidationError(card) {
		if (!card.file) return 'Choose an audio file.';
		if (!card.title.trim()) return 'Title is required.';
		if (!card.artist.trim()) return 'Artist is required.';
		if (!card.album.trim()) return 'Album is required.';
		return '';
	}

	/** @param {SongCard} card @param {string} activeBatchId */
	async function submitCard(card, activeBatchId) {
		cards = cards.map((item) =>
			item.key === card.key ? { ...item, status: 'queued', error: '' } : item
		);
		try {
			const job = await enqueueCatalogTrack({
				batchId: activeBatchId,
				file: /** @type {File} */ (card.file),
				title: card.title.trim(),
				artist: card.artist.trim(),
				album: card.album.trim(),
				genre: card.genre.trim() || undefined,
				lyrics: card.lyrics.trim() || undefined,
				visibility: card.visibility,
				cover: card.cover
			});
			cards = cards.map((item) =>
				item.key === card.key
					? {
							...item,
							status: /** @type {SongCard['status']} */ (job.status),
							jobId: job.jobId,
							filename: job.filename,
							error: job.error || '',
							locked: true
						}
					: item
			);
		} catch (requestError) {
			cards = cards.map((item) =>
				item.key === card.key
					? {
							...item,
							status: 'failed',
							error:
								requestError instanceof Error ? requestError.message : 'Could not queue this file.'
						}
					: item
			);
		}
	}

	async function uploadAll() {
		if (uploading) return;
		const errors = cards.map(cardValidationError);
		if (errors.some(Boolean)) {
			cards = cards.map((card, index) => ({ ...card, error: errors[index] }));
			formError = 'Fix the highlighted songs before uploading.';
			return;
		}
		formError = '';
		uploading = true;
		const activeBatchId =
			typeof crypto !== 'undefined' && crypto.randomUUID
				? crypto.randomUUID()
				: `batch-${Date.now()}-${Math.random().toString(36).slice(2)}`;
		persistBatchId(activeBatchId);
		subscribeLive(activeBatchId);
		await Promise.all(cards.map((card) => submitCard(card, activeBatchId)));
		// One immediate catch-up fetch, in case processing (or even full
		// completion, for a small/fast file) raced ahead of both the
		// response above and the live subscription -- the periodic fallback
		// below is only for whatever happens *after* this point.
		await refreshBatch(activeBatchId);
		scheduleFallbackPoll(activeBatchId);
	}

	function startNewBatch() {
		stopFallbackPolling();
		unsubscribeLive?.();
		unsubscribeLive = null;
		clearPersistedBatch();
		uploading = false;
		formError = '';
		cards = [blankCard()];
	}

	/** @param {SongCard} card */
	async function retryCard(card) {
		if (!card.jobId) return;
		try {
			const job = await retryCatalogJob(card.jobId);
			applyJobUpdate(job);
			uploading = true;
			if (batchId) scheduleFallbackPoll(batchId);
		} catch (requestError) {
			cards = cards.map((item) =>
				item.key === card.key
					? {
							...item,
							error:
								requestError instanceof Error ? requestError.message : 'Could not retry this song.'
						}
					: item
			);
		}
	}

	/** @param {SongCard} card */
	async function cancelCard(card) {
		if (!card.jobId) return;
		try {
			const job = await cancelCatalogJob(card.jobId);
			applyJobUpdate(job);
		} catch (requestError) {
			cards = cards.map((item) =>
				item.key === card.key
					? {
							...item,
							error:
								requestError instanceof Error ? requestError.message : 'Could not cancel this song.'
						}
					: item
			);
		}
	}

	/** @param {SongCard['status']} status */
	function statusLabel(status) {
		switch (status) {
			case 'idle':
				return 'Not uploaded';
			case 'queued':
				return 'Queued';
			case 'validating':
				return 'Validating';
			case 'storing':
				return 'Uploading';
			case 'analyzing':
				return 'Analyzing';
			case 'completed':
				return 'Uploaded';
			case 'cancelled':
				return 'Cancelled';
			default:
				return 'Failed';
		}
	}
</script>

<svelte:head><title>Upload music | Cuemix</title></svelte:head>

{#if $authStore.status !== 'authenticated'}
	<main class="upload-page">
		<p class="redirect-notice">
			{$authStore.status === 'checking' ? 'Checking your session…' : 'Redirecting to sign in…'}
		</p>
	</main>
{:else}
	<main class="upload-page">
		<header>
			<p class="eyebrow">Grow the catalog</p>
			<h1>Upload music</h1>
			<p>
				Add tracks to the AI-DJ catalog. Add as many songs as you like, then upload them all at
				once. You can leave this page or refresh it -- uploads keep going in the background and pick
				back up right here when you return.
			</p>
		</header>

		{#if restoring}<p class="restore-notice">Reconnecting to your upload in progress…</p>{/if}
		{#if formError}<div class="message error" role="alert">{formError}</div>{/if}

		{#if batchId}
			<section class="batch-progress card" aria-live="polite">
				<div class="batch-progress-head">
					<strong>{batchDone ? 'Batch finished' : 'Uploading…'}</strong>
					<span>{settledCount} of {cards.length} done</span>
				</div>
				<div
					class="progress-track"
					role="progressbar"
					aria-valuenow={overallPercent}
					aria-valuemin="0"
					aria-valuemax="100"
				>
					<div class="progress-fill" style={`width: ${overallPercent}%`}></div>
				</div>
				{#if failedCount || cancelledCount}
					<p class="batch-note">
						{#if failedCount}{failedCount} failed.{/if}
						{#if cancelledCount}{cancelledCount} cancelled.{/if}
					</p>
				{/if}
				{#if batchDone}
					<button type="button" class="secondary-button" onclick={startNewBatch}
						>Upload more songs</button
					>
				{/if}
			</section>
		{/if}

		<div class="song-list">
			{#each cards as card (card.key)}
				<article class="song-card card">
					<div class="song-card-head">
						<span
							class="status-pill"
							class:completed={card.status === 'completed'}
							class:failed={card.status === 'failed'}
							class:cancelled={card.status === 'cancelled'}
							class:busy={ACTIVE_STATUSES.has(card.status)}
						>
							{statusLabel(card.status)}
						</span>
						{#if cards.length > 1 && card.status === 'idle'}
							<button
								type="button"
								class="remove-button"
								onclick={() => removeCard(card.key)}
								disabled={uploading}>Remove</button
							>
						{/if}
					</div>

					{#if card.track?.coverUrl}
						<img class="cover-thumb" src={card.track.coverUrl} alt="" />
					{/if}

					<label class="field">
						<span>Audio file</span>
						<input
							type="file"
							accept={ACCEPTED_TYPES}
							disabled={card.locked}
							onchange={(event) => selectFile(card.key, event)}
						/>
						<small class="format-hint">Supported audio: MP3, WAV, OGG, FLAC</small>
						{#if card.file}<small class="file-name">{card.file.name}</small>
						{:else if card.filename}<small class="file-name">{card.filename}</small>{/if}
					</label>

					<label class="field">
						<span>Cover art (optional)</span>
						<input
							type="file"
							accept={ACCEPTED_COVER_TYPES}
							disabled={card.locked}
							onchange={(event) => selectCover(card.key, event)}
						/>
						<small class="format-hint">JPG, PNG, or WebP</small>
						{#if card.cover}<small class="file-name">{card.cover.name}</small>{/if}
					</label>

					<div class="field-grid">
						<label class="field">
							<span>Title</span>
							<input bind:value={card.title} maxlength="255" required disabled={card.locked} />
						</label>
						<label class="field">
							<span>Artist</span>
							<input bind:value={card.artist} maxlength="255" required disabled={card.locked} />
						</label>
						<label class="field">
							<span>Album</span>
							<input bind:value={card.album} maxlength="255" required disabled={card.locked} />
						</label>
						<label class="field">
							<span>Genre (optional)</span>
							<input bind:value={card.genre} maxlength="100" disabled={card.locked} />
						</label>
						<label class="field visibility">
							<span>Visibility</span>
							<select bind:value={card.visibility} disabled={card.locked}>
								<option value="private">Private (only you)</option>
								<option value="public">Public</option>
							</select>
						</label>
					</div>

					<label class="field">
						<span>Lyrics (optional)</span>
						<textarea bind:value={card.lyrics} maxlength="20000" disabled={card.locked}></textarea>
					</label>

					{#if card.error}<p class="card-error" role="alert">{card.error}</p>{/if}
					<div class="card-actions">
						{#if card.status === 'failed'}
							<button type="button" class="secondary-button" onclick={() => retryCard(card)}
								>Retry this song</button
							>
						{/if}
						{#if card.status === 'queued'}
							<button type="button" class="secondary-button" onclick={() => cancelCard(card)}
								>Cancel</button
							>
						{/if}
					</div>
				</article>
			{/each}
		</div>

		<div class="page-actions">
			<button type="button" class="secondary-button" onclick={addCard} disabled={uploading}>
				+ Add more sound file
			</button>
			<button
				type="button"
				class="primary-button"
				onclick={uploadAll}
				disabled={uploading || batchDone}
			>
				{uploading ? 'Uploading…' : 'Upload All'}
			</button>
		</div>
	</main>
{/if}

<style>
	.upload-page {
		max-width: 900px;
		margin: 0 auto;
		padding: 48px 0 180px;
	}
	.redirect-notice {
		display: grid;
		min-height: 40vh;
		place-content: center;
		color: var(--text-muted);
	}
	.restore-notice {
		color: var(--text-muted);
		font-size: 13px;
	}
	.eyebrow {
		margin: 0;
		color: var(--accent-2);
		font-weight: 900;
		letter-spacing: 0.14em;
		text-transform: uppercase;
	}
	h1 {
		margin: 8px 0;
		font-size: clamp(38px, 6vw, 60px);
		letter-spacing: -0.05em;
	}
	header > p:last-child {
		color: var(--text-soft);
	}
	.message {
		padding: 16px 20px;
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-md);
		margin: 20px 0;
	}
	.message.error {
		border-color: rgba(255, 107, 134, 0.45);
		color: var(--danger);
	}
	.card {
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-md);
		background: rgba(7, 16, 31, 0.92);
	}
	.batch-progress {
		display: grid;
		gap: 10px;
		padding: 18px 20px;
		margin: 24px 0;
	}
	.batch-progress-head {
		display: flex;
		justify-content: space-between;
		gap: 10px;
		color: var(--text-soft);
	}
	.progress-track {
		height: 8px;
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.08);
		overflow: hidden;
	}
	.progress-fill {
		height: 100%;
		border-radius: 999px;
		background: var(--accent);
		transition: width 0.3s ease;
	}
	.batch-note {
		margin: 0;
		color: var(--danger);
		font-size: 13px;
	}
	.song-list {
		display: grid;
		gap: 18px;
		margin: 28px 0;
	}
	.song-card {
		display: grid;
		gap: 12px;
		padding: 20px;
	}
	.song-card-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.cover-thumb {
		width: 72px;
		height: 72px;
		border-radius: 12px;
		object-fit: cover;
		border: 1px solid var(--border-soft);
	}
	.status-pill {
		border-radius: 999px;
		padding: 4px 10px;
		background: rgba(255, 255, 255, 0.08);
		color: var(--text-soft);
		font-size: 12px;
		font-weight: 800;
	}
	.status-pill.busy {
		background: rgba(59, 130, 246, 0.18);
		color: var(--accent-2);
	}
	.status-pill.completed {
		background: rgba(112, 225, 199, 0.14);
		color: var(--success);
	}
	.status-pill.failed {
		background: rgba(255, 107, 134, 0.16);
		color: var(--danger);
	}
	.status-pill.cancelled {
		background: rgba(255, 255, 255, 0.08);
		color: var(--text-muted);
	}
	.remove-button {
		border: 0;
		background: none;
		color: var(--text-muted);
		font-size: 12px;
		font-weight: 800;
	}
	.field {
		display: grid;
		gap: 6px;
		font-weight: 800;
		color: var(--text-soft);
		font-size: 13px;
	}
	.format-hint {
		color: var(--text-muted);
		font-weight: 500;
	}
	.field-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
	}
	.visibility {
		grid-column: 1 / -1;
	}
	input,
	select,
	textarea {
		width: 100%;
		border: 1px solid var(--border-soft);
		border-radius: 12px;
		padding: 11px 12px;
		background: #050b16;
		color: var(--text-main);
		font-weight: 500;
	}
	input:disabled,
	select:disabled,
	textarea:disabled {
		opacity: 0.6;
	}
	textarea {
		min-height: 80px;
		resize: vertical;
	}
	.file-name {
		color: var(--text-muted);
	}
	.card-error {
		margin: 0;
		color: var(--danger);
		font-size: 13px;
	}
	.card-actions {
		display: flex;
		gap: 10px;
	}
	.page-actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 12px;
	}
	.primary-button,
	.secondary-button {
		min-height: 44px;
		border-radius: 999px;
		padding: 10px 18px;
		font-weight: 800;
	}
	.primary-button {
		border: 0;
		background: var(--accent);
		color: white;
	}
	.secondary-button {
		border: 1px solid var(--border-soft);
		background: transparent;
		color: var(--text-soft);
	}
	.primary-button:disabled,
	.secondary-button:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}
	@media (max-width: 640px) {
		.field-grid {
			grid-template-columns: 1fr;
		}
		.page-actions {
			flex-direction: column;
		}
	}
</style>
