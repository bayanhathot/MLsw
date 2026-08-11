<script>
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
	}

	function timeUpdated() {
		if (!audioElement) return;
		const range = bounds();
		currentTime = Math.max(0, audioElement.currentTime - range.start);
		duration = range.length;
		if (range.end > range.start && audioElement.currentTime >= range.end - 0.05) advance();
	}

	/** @param {number} nextIndex */
	function goTo(nextIndex) {
		if (nextIndex < 0 || nextIndex >= playableSegments.length) return;
		index = nextIndex;
		currentTime = 0;
		duration = 0;
		completedUrl = '';
		error = '';
	}

	function advance() {
		if (completedUrl === audioUrl) return;
		completedUrl = audioUrl;
		if (hasNext) {
			goTo(index + 1);
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
		}
		shouldPlay = !shouldPlay;
		error = '';
	}
</script>

<aside class="mini-player" aria-label="Mix player">
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
	<button class="close" type="button" aria-label="Close mix player" onclick={onClose}>Close</button>
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
			onplay={() => (isPlaying = true)}
			onplaying={() => (error = '')}
			onpause={() => (isPlaying = false)}
			onerror={() => {
				shouldPlay = false;
				error = 'This segment could not be loaded.';
			}}
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
		grid-template-columns: minmax(180px, 1fr) auto minmax(180px, 2fr) auto;
		gap: 18px;
		align-items: center;
		padding: 16px;
		border: 1px solid var(--accent-2);
		border-radius: var(--radius-md);
		background: #07101f;
		box-shadow: var(--shadow-soft);
	}
	.details {
		display: grid;
		min-width: 0;
	}
	.details span {
		color: var(--accent-2);
		font-size: 12px;
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
		background: transparent;
		color: var(--text-main);
	}
	button.play {
		background: var(--accent);
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
	@media (max-width: 800px) {
		.mini-player {
			grid-template-columns: 1fr auto;
		}
		.transport {
			justify-self: end;
		}
		.time {
			grid-column: 1 / -1;
		}
	}
</style>
