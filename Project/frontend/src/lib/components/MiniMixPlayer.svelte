<script>
	import { onDestroy } from 'svelte';
	import { authStore } from '$lib/stores/authStore.js';
	import { recordListeningEvent } from '$lib/services/listeningApi.js';

	/** @type {{ mix: import('$lib/types.js').Mix, onClose?: () => void }} */
	let { mix, onClose = () => {} } = $props();

	let index = $state(0);
	let shouldPlay = $state(true);
	let isPlaying = $state(false);
	let currentTime = $state(0);
	let duration = $state(0);
	let error = $state('');
	let completedUrl = $state('');
	/** @type {HTMLAudioElement | null} */
	let audioElement = $state(null);
	let playableSegments = $derived(mix.segments.filter((item) => Boolean(item.audioUrl)));
	let segment = $derived(playableSegments[index]);
	let audioUrl = $derived(segment?.audioUrl || '');
	let hasPrevious = $derived(index > 0);
	let hasNext = $derived(index < playableSegments.length - 1);

	let trackingEventId = '';
	let trackingMixId = 0;
	let trackingSegmentId = 0;
	/** @type {Date | null} */
	let trackingStartedAt = null;
	let listenedSeconds = 0;
	/** @type {number | null} */
	let lastMediaPosition = null;
	let eventFlushed = false;
	let trackedMixId = $state(/** @type {number | null} */ (null));

	$effect(() => {
		if (trackedMixId === null) {
			trackedMixId = mix.id;
			return;
		}
		if (mix.id !== trackedMixId) {
			void flushListening(true, true);
			trackedMixId = mix.id;
			index = 0;
			resetTracking();
		}
	});

	$effect(() => {
		if (!audioElement || !audioUrl) return;
		if (shouldPlay) {
			void audioElement.play().catch(() => {
				shouldPlay = false;
				error = 'Press play to start this mix.';
			});
		} else if (!audioElement.paused) {
			audioElement.pause();
		}
	});

	onDestroy(() => {
		void flushListening(true, true);
	});

	function makeEventId() {
		return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
			? `listen:${crypto.randomUUID()}`
			: `listen:${Date.now()}:${Math.random().toString(36).slice(2)}`;
	}

	function resetTracking() {
		trackingEventId = makeEventId();
		trackingMixId = Number(mix?.id || 0);
		trackingSegmentId = Number(segment?.id || 0);
		trackingStartedAt = null;
		listenedSeconds = 0;
		lastMediaPosition = null;
		eventFlushed = false;
	}

	/** @param {boolean} skipped @param {boolean} [keepalive] */
	async function flushListening(skipped, keepalive = false) {
		if (
			eventFlushed ||
			$authStore.status !== 'authenticated' ||
			!trackingSegmentId ||
			!trackingMixId ||
			!trackingStartedAt ||
			listenedSeconds < 0.75
		) {
			return;
		}
		eventFlushed = true;
		try {
			await recordListeningEvent({
				clientEventId: trackingEventId,
				mixId: trackingMixId,
				segmentId: trackingSegmentId,
				startedAt: trackingStartedAt.toISOString(),
				endedAt: new Date().toISOString(),
				secondsListened: listenedSeconds,
				skipped,
				keepalive
			});
		} catch (requestError) {
			// Analytics must never interrupt playback. Keep the error in devtools
			// so the event pipeline can still be debugged.
			console.warn('Zonix listening event was not recorded.', requestError);
		}
	}

	/** @param {number} seconds */
	function formatTime(seconds) {
		if (!Number.isFinite(seconds) || seconds <= 0) return '0:00';
		return `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60)
			.toString()
			.padStart(2, '0')}`;
	}

	function bounds() {
		const mediaDuration =
			audioElement && Number.isFinite(audioElement.duration) ? audioElement.duration : 0;
		const start = Math.max(0, segment?.startSecond || 0);
		const requestedEnd = segment?.endSecond || 0;
		const end =
			requestedEnd > start ? Math.min(requestedEnd, mediaDuration || requestedEnd) : mediaDuration;
		return { start, end, length: Math.max(0, end - start) };
	}

	function loaded() {
		if (!audioElement) return;
		const range = bounds();
		audioElement.currentTime = range.start;
		currentTime = 0;
		duration = range.length;
		completedUrl = '';
		resetTracking();
	}

	function mediaPlaying() {
		isPlaying = true;
		error = '';
		if (!trackingStartedAt) trackingStartedAt = new Date();
		lastMediaPosition = audioElement?.currentTime ?? null;
	}

	function mediaPaused() {
		isPlaying = false;
		lastMediaPosition = null;
	}

	function timeUpdated() {
		if (!audioElement) return;
		const absolute = audioElement.currentTime;
		if (isPlaying && lastMediaPosition !== null) {
			const delta = absolute - lastMediaPosition;
			// Ignore seeks/jumps; only real forward playback contributes.
			if (delta > 0 && delta <= 2.5) listenedSeconds += delta;
		}
		lastMediaPosition = absolute;

		const range = bounds();
		currentTime = Math.max(0, absolute - range.start);
		duration = range.length;
		if (range.end > range.start && absolute >= range.end - 0.05) advance();
	}

	/** @param {number} nextIndex @param {boolean} [skipped] @param {boolean} [flushCurrent] */
	function goTo(nextIndex, skipped = true, flushCurrent = true) {
		if (nextIndex < 0 || nextIndex >= playableSegments.length) return;
		if (flushCurrent) void flushListening(skipped);
		index = nextIndex;
		currentTime = 0;
		duration = 0;
		completedUrl = '';
		error = '';
		lastMediaPosition = null;
	}

	function advance() {
		if (completedUrl === audioUrl) return;
		completedUrl = audioUrl;
		void flushListening(false);
		if (hasNext) {
			goTo(index + 1, false, false);
		} else {
			shouldPlay = false;
			isPlaying = false;
			currentTime = duration;
		}
	}

	function togglePlay() {
		if (!audioUrl) return;
		const range = bounds();
		if (
			!shouldPlay &&
			audioElement &&
			(audioElement.ended ||
				(range.end > range.start && audioElement.currentTime >= range.end - 0.05))
		) {
			audioElement.currentTime = range.start;
			completedUrl = '';
			currentTime = 0;
			resetTracking();
		}
		shouldPlay = !shouldPlay;
		error = '';
	}

	function closePlayer() {
		void flushListening(true, true);
		onClose();
	}

	function mediaError() {
		shouldPlay = false;
		void flushListening(true);
		error = 'This segment could not be loaded.';
	}
</script>

<aside class="mini-player" aria-label="Mix player">
	<div class="art" style={`background-image: url('${segment?.coverUrl || mix.coverUrl || ''}')`}>
		{#if !segment?.coverUrl && !mix.coverUrl}<span>ZX</span>{/if}
	</div>
	<div class="details">
		<span>Now playing · {index + 1}/{playableSegments.length}</span>
		<strong>{mix.title}</strong>
		<small>{segment?.title} — {segment?.artist}</small>
	</div>
	<div class="transport">
		<button
			type="button"
			disabled={!hasPrevious}
			aria-label="Previous mix segment"
			onclick={() => goTo(index - 1)}>⏮</button
		>
		<button
			class="play"
			type="button"
			aria-label={isPlaying ? 'Pause mix' : 'Play mix'}
			aria-pressed={isPlaying}
			onclick={togglePlay}>{isPlaying ? 'Ⅱ' : '▶'}</button
		>
		<button
			type="button"
			disabled={!hasNext}
			aria-label="Next mix segment"
			onclick={() => goTo(index + 1)}>⏭</button
		>
	</div>
	<div class="time" aria-label="Playback progress">
		<span>{formatTime(currentTime)}</span>
		<progress value={currentTime} max={duration || 1}></progress>
		<span>{formatTime(duration)}</span>
	</div>
	<button class="close" type="button" aria-label="Close mix player" onclick={closePlayer}
		>Close</button
	>
	{#if error}<p role="status">{error}</p>{/if}
	{#if audioUrl}
		<audio
			bind:this={audioElement}
			class="audio"
			src={audioUrl}
			preload="metadata"
			onloadedmetadata={loaded}
			ontimeupdate={timeUpdated}
			onended={advance}
			onplay={mediaPlaying}
			onplaying={() => (error = '')}
			onpause={mediaPaused}
			onerror={mediaError}
		></audio>
	{/if}
</aside>

<style>
	.mini-player {
		position: fixed;
		right: 16px;
		bottom: 16px;
		left: 16px;
		z-index: 50;
		display: grid;
		grid-template-columns: auto minmax(180px, 1fr) auto minmax(180px, 2fr) auto;
		gap: 16px;
		align-items: center;
		padding: 14px 16px;
		border: 1px solid rgba(125, 183, 255, 0.34);
		border-radius: 22px;
		background: linear-gradient(180deg, rgba(8, 18, 34, 0.97), rgba(4, 9, 18, 0.98));
		box-shadow:
			0 22px 80px rgba(0, 0, 0, 0.62),
			0 0 50px rgba(59, 130, 246, 0.11);
		backdrop-filter: blur(20px);
	}
	.art {
		display: grid;
		width: 52px;
		height: 52px;
		place-items: center;
		border: 1px solid var(--border-soft);
		border-radius: 14px;
		background: linear-gradient(135deg, #183862, #6b8cff);
		background-position: center;
		background-size: cover;
		color: white;
		font-weight: 900;
	}
	.details {
		display: grid;
		min-width: 0;
	}
	.details span {
		color: var(--accent-2);
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}
	.details strong,
	.details small {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.details small {
		color: var(--text-muted);
	}
	.transport,
	.time {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	button {
		min-width: 38px;
		min-height: 38px;
		border: 1px solid var(--border-soft);
		border-radius: 999px;
		background: rgba(125, 183, 255, 0.05);
		color: var(--text-main);
	}
	button.play {
		width: 46px;
		height: 46px;
		border: 0;
		background: linear-gradient(135deg, #2f6fee, #7d9cff);
		box-shadow: var(--shadow-blue);
		color: white;
	}
	button.close {
		padding: 8px 13px;
	}
	button:disabled {
		cursor: not-allowed;
		opacity: 0.4;
	}
	.time {
		color: var(--text-muted);
		font-size: 12px;
	}
	progress {
		width: 100%;
		accent-color: var(--accent-2);
	}
	p {
		grid-column: 1 / -1;
		margin: 0;
		color: #ffb1bf;
		font-size: 13px;
	}
	.audio {
		display: none;
	}
	@media (max-width: 850px) {
		.mini-player {
			grid-template-columns: auto 1fr auto;
		}
		.transport {
			justify-self: end;
		}
		.time {
			grid-column: 1 / -1;
		}
		.close {
			position: absolute;
			top: 8px;
			right: 8px;
		}
	}
</style>
