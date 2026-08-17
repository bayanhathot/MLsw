<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onDestroy } from 'svelte';

	import { enqueueCatalogTrack, getCatalogBatchStatus } from '$lib/services/catalogApi.js';
	import { authStore } from '$lib/stores/authStore.js';

	const ACCEPTED_TYPES = 'audio/mpeg,audio/wav,audio/ogg,audio/flac';

	/** @typedef {{
	 * key: number,
	 * file: File | null,
	 * title: string,
	 * artist: string,
	 * album: string,
	 * genre: string,
	 * lyrics: string,
	 * visibility: 'private' | 'public',
	 * status: 'idle' | 'queued' | 'processing' | 'completed' | 'failed',
	 * error: string,
	 * jobId: string | null
	 * }} SongCard */

	let nextKey = 1;
	/** @returns {SongCard} */
	function blankCard() {
		return {
			key: nextKey++,
			file: null,
			title: '',
			artist: '',
			album: '',
			genre: '',
			lyrics: '',
			visibility: 'private',
			status: 'idle',
			error: '',
			jobId: null
		};
	}

	/** @type {SongCard[]} */
	let cards = $state([blankCard()]);
	let uploading = $state(false);
	/** @type {string | null} */
	let batchId = $state(null);
	let formError = $state('');
	let pollHandle = /** @type {ReturnType<typeof setTimeout> | null} */ (null);

	let batchDone = $derived(
		batchId !== null &&
			cards.every((card) => card.status === 'completed' || card.status === 'failed')
	);
	let completedCount = $derived(cards.filter((card) => card.status === 'completed').length);
	let failedCount = $derived(cards.filter((card) => card.status === 'failed').length);
	let overallPercent = $derived(
		cards.length ? Math.round(((completedCount + failedCount) / cards.length) * 100) : 0
	);

	$effect(() => {
		if ($authStore.status === 'guest') {
			void goto(resolve('/login'));
		}
	});

	onDestroy(() => {
		if (pollHandle) clearTimeout(pollHandle);
	});

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

	/** @param {SongCard} card */
	function cardValidationError(card) {
		if (!card.file) return 'Choose an audio file.';
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
				title: card.title.trim() || undefined,
				artist: card.artist.trim(),
				album: card.album.trim(),
				genre: card.genre.trim() || undefined,
				lyrics: card.lyrics.trim() || undefined,
				visibility: card.visibility
			});
			cards = cards.map((item) =>
				item.key === card.key
					? {
							...item,
							status: job.status === 'failed' ? 'failed' : 'queued',
							jobId: job.jobId,
							error: job.error || ''
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

	/** @param {string} activeBatchId */
	async function pollBatch(activeBatchId) {
		try {
			const status = await getCatalogBatchStatus(activeBatchId);
			const byJobId = new Map(status.jobs.map((job) => [job.jobId, job]));
			cards = cards.map((card) => {
				const job = card.jobId ? byJobId.get(card.jobId) : null;
				if (!job) return card;
				return {
					...card,
					status: /** @type {SongCard['status']} */ (job.status),
					error: job.error || ''
				};
			});
		} catch {
			// Best-effort polling -- a transient failure just retries on the
			// next tick instead of surfacing as a page-level error.
		}
		if (cards.some((card) => card.status === 'queued' || card.status === 'processing')) {
			pollHandle = setTimeout(() => void pollBatch(activeBatchId), 1200);
		} else {
			uploading = false;
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
		batchId = activeBatchId;
		await Promise.all(cards.map((card) => submitCard(card, activeBatchId)));
		void pollBatch(activeBatchId);
	}

	function startNewBatch() {
		if (pollHandle) clearTimeout(pollHandle);
		batchId = null;
		uploading = false;
		formError = '';
		cards = [blankCard()];
	}

	/** @param {SongCard} card */
	function retryCard(card) {
		if (!batchId || uploading) return;
		uploading = true;
		const activeBatchId = batchId;
		void submitCard(card, activeBatchId).then(() => void pollBatch(activeBatchId));
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
				once.
			</p>
		</header>

		{#if formError}<div class="message error" role="alert">{formError}</div>{/if}

		{#if batchId}
			<section class="batch-progress card" aria-live="polite">
				<div class="batch-progress-head">
					<strong>{batchDone ? 'Batch finished' : 'Uploading…'}</strong>
					<span>{completedCount + failedCount} of {cards.length} done</span>
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
				{#if failedCount}<p class="batch-note">{failedCount} of {cards.length} failed.</p>{/if}
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
							class:busy={card.status === 'queued' || card.status === 'processing'}
						>
							{#if card.status === 'idle'}Not uploaded
							{:else if card.status === 'queued'}Queued
							{:else if card.status === 'processing'}Processing
							{:else if card.status === 'completed'}Uploaded
							{:else}Failed{/if}
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

					<label class="field">
						<span>Audio file</span>
						<input
							type="file"
							accept={ACCEPTED_TYPES}
							disabled={uploading && card.status !== 'idle'}
							onchange={(event) => selectFile(card.key, event)}
						/>
						{#if card.file}<small class="file-name">{card.file.name}</small>{/if}
					</label>

					<div class="field-grid">
						<label class="field">
							<span>Title (optional)</span>
							<input bind:value={card.title} maxlength="255" disabled={uploading} />
						</label>
						<label class="field">
							<span>Artist</span>
							<input bind:value={card.artist} maxlength="255" required disabled={uploading} />
						</label>
						<label class="field">
							<span>Album</span>
							<input bind:value={card.album} maxlength="255" required disabled={uploading} />
						</label>
						<label class="field">
							<span>Genre (optional)</span>
							<input bind:value={card.genre} maxlength="100" disabled={uploading} />
						</label>
						<label class="field visibility">
							<span>Visibility</span>
							<select bind:value={card.visibility} disabled={uploading}>
								<option value="private">Private (only you)</option>
								<option value="public">Public</option>
							</select>
						</label>
					</div>

					<label class="field">
						<span>Lyrics (optional)</span>
						<textarea bind:value={card.lyrics} maxlength="20000" disabled={uploading}></textarea>
					</label>

					{#if card.error}<p class="card-error" role="alert">{card.error}</p>{/if}
					{#if card.status === 'failed' && batchId && !uploading}
						<button type="button" class="secondary-button" onclick={() => retryCard(card)}
							>Retry this song</button
						>
					{/if}
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
