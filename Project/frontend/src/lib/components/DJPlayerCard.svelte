<script>
	import { onDestroy } from 'svelte';
	import { APP_STATES } from '$lib/constants/appStates.js';
	import { authStore } from '$lib/stores/authStore.js';
	import { recordListeningEvent } from '$lib/services/listeningApi.js';
	import { playerStore } from '$lib/stores/playerStore.js';

	const COACH_OPTIONS = ['Good vibe', 'More energy', 'Less vocals', 'Smoother'];

	/**
	 * @typedef {import('$lib/types.js').AppStatus} AppStatus
	 * @typedef {import('$lib/types.js').Session} Session
	 */

	/** @type {{
	 * defaultCompact?: boolean,
	 * status?: AppStatus,
	 * currentStep?: string,
	 * progress?: number,
	 * session?: Session | null,
	 * isPlaying?: boolean,
	 * playbackRequested?: boolean,
	 * isPlaybackBuffering?: boolean,
	 * hasEnded?: boolean,
	 * isStopping?: boolean,
	 * isFeedbackPending?: boolean,
	 * pendingFeedback?: string | null,
	 * isChangingVibe?: boolean,
	 * selectedFeedback?: string | null,
	 * playbackError?: string | null,
	 * onTogglePlay?: () => void,
	 * onStop?: () => void,
	 * onFeedback?: (feedback: string) => void,
	 * onMediaPlaying?: () => void,
	 * onMediaPaused?: () => void,
	 * onMediaWaiting?: () => void,
	 * onMediaReady?: () => void,
	 * onMediaEnded?: () => void,
	 * onMediaError?: (message: string) => void,
	 * onPrepareNext?: () => Promise<string | null>
	 * }} */
	let {
		defaultCompact = false,
		status = APP_STATES.IDLE,
		currentStep = '',
		progress = 0,
		session = null,
		isPlaying = false,
		playbackRequested = false,
		isPlaybackBuffering = false,
		hasEnded = false,
		isStopping = false,
		isFeedbackPending = false,
		pendingFeedback = null,
		isChangingVibe = false,
		selectedFeedback = null,
		playbackError = null,
		onTogglePlay = () => {},
		onStop = () => {},
		onFeedback = () => {},
		onMediaPlaying = () => {},
		onMediaPaused = () => {},
		onMediaWaiting = () => {},
		onMediaReady = () => {},
		onMediaEnded = () => {},
		onMediaError = () => {},
		onPrepareNext = () => Promise.resolve(null)
	} = $props();

	let volume = $state(72);
	// Writable derived: resets to the route's default whenever it flips
	// (entering/leaving Studio), but a manual toggle in between overrides it
	// until that happens, same as the $state+$effect mirror this replaced.
	let compact = $derived(defaultCompact);
	/** @type {HTMLAudioElement | null} */
	let audioElement = $state(null);
	let segmentIndex = $state(0);
	let currentTime = $state(0);
	let duration = $state(0);
	let trackedSessionId = $state('');
	let trackedNowPlayingKey = $state('');
	let completedAudioUrl = $state('');
	let trackingEventId = '';
	let trackingSessionId = '';
	/** @type {Date | null} */
	let trackingStartedAt = null;
	let listenedSeconds = 0;
	/** @type {number | null} */
	let lastMediaPosition = null;
	let eventFlushed = false;
	// Which audioUrl prepareNext() has already been fired for -- guards
	// against re-firing on every timeupdate tick once the threshold is
	// crossed (design doc 4.1: "at most once per segment"). Reset below
	// whenever audioUrl itself changes.
	let preparedForUrl = $state('');
	// The next track's audio URL, once prepareNext() resolves with one --
	// drives the optional hidden preload <audio> element (design doc 4.3).
	let preloadAudioUrl = $state('');

	let segments = $derived(session?.segments ?? []);
	let activeSegment = $derived(segments[segmentIndex] ?? null);
	let nowPlaying = $derived(
		activeSegment
			? {
					title: activeSegment.title,
					artist: activeSegment.artist,
					coverUrl: activeSegment.coverUrl || session?.nowPlaying.coverUrl || ''
				}
			: session?.nowPlaying
	);
	let audioUrl = $derived(activeSegment?.audioUrl || session?.audioUrl || '');
	// Both this bar and MiniMixPlayer.svelte are independently
	// position:fixed/bottom-docked -- now that this card is mounted globally
	// (routes/+layout.svelte) instead of only on the home route, a saved mix
	// played from another page while a DJ session is also active would
	// otherwise overlap it directly. Stack above it instead.
	let mixPlayerActive = $derived(Boolean($playerStore.mix));
	let canControl = $derived(status === APP_STATES.PLAYING && Boolean(audioUrl));
	let isStarting = $derived(status === APP_STATES.STARTING);
	let hasPrevious = $derived(segmentIndex > 0);
	let hasNext = $derived(segmentIndex < segments.length - 1);
	let progressPercent = $derived(duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0);
	let playLabel = $derived(
		isPlaybackBuffering && playbackRequested
			? 'Loading audio'
			: isPlaying
				? 'Pause AI DJ'
				: hasEnded
					? 'Replay AI DJ'
					: 'Play AI DJ'
	);

	$effect(() => {
		const sessionId = session?.id || '';
		const playingKey = sessionId ? `${sessionId}:${nowPlaying?.title || ''}:${segmentIndex}` : '';
		if (sessionId !== trackedSessionId) {
			void flushListening(true, true);
			trackedSessionId = sessionId;
			trackedNowPlayingKey = playingKey;
			segmentIndex = 0;
			currentTime = 0;
			duration = 0;
			completedAudioUrl = '';
			resetTracking();
		} else if (playingKey && playingKey !== trackedNowPlayingKey) {
			void flushListening(true);
			trackedNowPlayingKey = playingKey;
			resetTracking();
		}
	});

	$effect(() => {
		if (audioElement) {
			audioElement.volume = volume / 100;
		}
	});

	$effect(() => {
		// audioUrl is the reactive dependency this effect re-runs on -- a new
		// segment/track means any prior prepare/preload was for a URL that's
		// no longer current.
		void audioUrl;
		preparedForUrl = '';
		preloadAudioUrl = '';
	});

	$effect(() => {
		if (!audioElement || !audioUrl) {
			return;
		}

		if (canControl && playbackRequested) {
			const bounds = segmentBounds();
			if (
				audioElement.ended ||
				(bounds.end > bounds.start && audioElement.currentTime >= bounds.end - 0.05)
			) {
				audioElement.currentTime = bounds.start;
				completedAudioUrl = '';
			}

			void audioElement.play().catch((error) => {
				const wasBlocked = error instanceof DOMException && error.name === 'NotAllowedError';
				onMediaError(
					wasBlocked
						? 'Autoplay was blocked. Press play to start the music.'
						: 'The audio could not start. Try playing it again.'
				);
			});
		} else if (!playbackRequested && !audioElement.paused) {
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
		trackingSessionId = session?.id || '';
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
			!trackingSessionId ||
			!trackingStartedAt ||
			listenedSeconds < 0.75
		)
			return;
		eventFlushed = true;
		try {
			await recordListeningEvent({
				clientEventId: trackingEventId,
				sessionId: trackingSessionId,
				startedAt: trackingStartedAt.toISOString(),
				endedAt: new Date().toISOString(),
				secondsListened: listenedSeconds,
				skipped,
				keepalive
			});
		} catch (requestError) {
			console.warn('Cuemix listening event was not recorded.', requestError);
		}
	}

	function trackedMediaPlaying() {
		if (!trackingStartedAt) trackingStartedAt = new Date();
		lastMediaPosition = audioElement?.currentTime ?? null;
		onMediaPlaying();
	}

	function trackedMediaPaused() {
		lastMediaPosition = null;
		onMediaPaused();
	}

	function toggleCompact() {
		compact = !compact;
	}

	function handleStopClick() {
		void flushListening(true, true);
		onStop();
	}

	/** @param {string} feedback */
	async function handleCoachFeedback(feedback) {
		// Flush the moment before the backend changes the session track key, so
		// listening analytics are attributed to what the user actually heard.
		await flushListening(true);
		onFeedback(feedback);
	}

	/** @param {number} seconds */
	function formatTime(seconds) {
		if (!Number.isFinite(seconds) || seconds <= 0) {
			return '0:00';
		}

		const minutes = Math.floor(seconds / 60);
		const remainingSeconds = Math.floor(seconds % 60)
			.toString()
			.padStart(2, '0');
		return `${minutes}:${remainingSeconds}`;
	}

	function segmentBounds() {
		const mediaDuration =
			audioElement && Number.isFinite(audioElement.duration) ? audioElement.duration : 0;
		const start = Math.max(0, activeSegment?.startSecond || 0);
		const requestedEnd = activeSegment?.endSecond || 0;
		const end =
			requestedEnd > start ? Math.min(requestedEnd, mediaDuration || requestedEnd) : mediaDuration;
		return { start, end, length: Math.max(0, end - start) };
	}

	/** @param {{ start: number, end: number, length: number }} bounds */
	function maybePrepareNext(bounds) {
		// Only meaningful right before this segment ending would actually
		// trigger a backend advance() (see handleAudioEnded below) -- if
		// there's already a next *local* segment queued, that transition
		// doesn't need the backend prepared ahead of time.
		if (hasNext || preparedForUrl === audioUrl || bounds.length <= 0) {
			return;
		}

		const remaining = bounds.length - currentTime;
		// Percentage-based, not a fixed second count (design doc 4.1): a fixed
		// threshold would fire far too early on a multi-minute Audius track,
		// or far too late (or never) on a ~45s catalog demo clip.
		const threshold = Math.max(10, bounds.length * 0.1);
		if (remaining > threshold) {
			return;
		}

		preparedForUrl = audioUrl;
		const firedForUrl = audioUrl;
		void onPrepareNext().then((nextAudioUrl) => {
			if (nextAudioUrl && preparedForUrl === firedForUrl) {
				preloadAudioUrl = nextAudioUrl;
			}
		});
	}

	function syncTimeline() {
		if (!audioElement) {
			return;
		}

		const absolute = audioElement.currentTime;
		if (isPlaying && lastMediaPosition !== null) {
			const delta = absolute - lastMediaPosition;
			if (delta > 0 && delta <= 2.5) listenedSeconds += delta;
		}
		lastMediaPosition = absolute;
		const bounds = segmentBounds();
		currentTime = Math.max(0, absolute - bounds.start);
		duration = bounds.length;
		maybePrepareNext(bounds);

		if (bounds.end > bounds.start && audioElement.currentTime >= bounds.end - 0.05) {
			handleAudioEnded();
		}
	}

	function handleLoadedMetadata() {
		if (!audioElement) {
			return;
		}

		const bounds = segmentBounds();
		if (audioElement.currentTime < bounds.start || audioElement.currentTime >= bounds.end) {
			audioElement.currentTime = bounds.start;
		}
		completedAudioUrl = '';
		resetTracking();
		syncTimeline();
	}

	/** @param {Event} event */
	function handleSeekInput(event) {
		const target = /** @type {HTMLInputElement} */ (event.currentTarget);
		if (!audioElement || duration <= 0) {
			return;
		}

		const bounds = segmentBounds();
		const nextTime = (Number(target.value) / 100) * bounds.length;
		audioElement.currentTime = bounds.start + nextTime;
		currentTime = nextTime;
		lastMediaPosition = audioElement.currentTime;
		completedAudioUrl = '';
	}

	/** @param {-1 | 1} direction */
	function changeSegment(direction) {
		const nextIndex = segmentIndex + direction;
		if (nextIndex < 0 || nextIndex >= segments.length) {
			return;
		}

		void flushListening(true);
		segmentIndex = nextIndex;
		currentTime = 0;
		duration = 0;
		completedAudioUrl = '';
		if (playbackRequested) {
			onMediaWaiting();
		}
	}

	function handleAudioEnded() {
		if (completedAudioUrl === audioUrl) {
			return;
		}

		completedAudioUrl = audioUrl;
		currentTime = duration;
		void flushListening(false);
		if (hasNext) {
			changeSegment(1);
		} else {
			onMediaEnded();
		}
	}

	function handleMediaError() {
		void flushListening(true);
		const code = audioElement?.error?.code;
		const suffix = code ? ` (media error ${code})` : '';
		onMediaError(`This audio source could not be loaded${suffix}.`);
	}

	/** @param {Event} event */
	function handleVolumeInput(event) {
		const target = /** @type {HTMLInputElement} */ (event.currentTarget);
		volume = Number(target.value);
	}
</script>

<section
	class="player-deck"
	class:stacked={mixPlayerActive}
	class:compact
	aria-label="Cuemix AI DJ player"
>
	<button
		class="compact-toggle"
		type="button"
		onclick={toggleCompact}
		aria-pressed={compact}
		aria-label={compact ? 'Expand DJ player' : 'Collapse DJ player'}
		title={compact ? 'Expand DJ player' : 'Collapse DJ player'}
	>
		<span aria-hidden="true">{compact ? '▲' : '▼'}</span>
	</button>

	<div class="track-block">
		{#if nowPlaying}
			{#if nowPlaying.coverUrl}
				<img class="cover" src={nowPlaying.coverUrl} alt="" />
			{:else}
				<div class="cover placeholder" aria-hidden="true">ZX</div>
			{/if}
			<div class="track-copy">
				<h2>{nowPlaying.title}</h2>
				<p>{nowPlaying.artist}</p>
			</div>
		{:else}
			<div class="cover placeholder" aria-hidden="true">ZX</div>
			<div class="track-copy">
				<h2>Cuemix is ready</h2>
				<p>Start a vibe to begin the flow.</p>
			</div>
		{/if}
	</div>

	{#if compact}
		<div class="compact-controls">
			<span class:active={isPlaying} class="signal" aria-hidden="true"></span>
			<button
				class="segment-button"
				type="button"
				disabled={!canControl || !hasPrevious}
				aria-label="Previous segment"
				onclick={() => changeSegment(-1)}>⏮</button
			>
			<button
				class="play-button small"
				type="button"
				onclick={onTogglePlay}
				disabled={!canControl || isStopping}
				aria-label={playLabel}
				aria-pressed={isPlaying}
			>
				{isPlaybackBuffering && playbackRequested ? '…' : isPlaying ? 'Ⅱ' : '▶'}
			</button>
			<button
				class="segment-button"
				type="button"
				disabled={!canControl || !hasNext}
				aria-label="Next segment"
				onclick={() => changeSegment(1)}>⏭</button
			>
		</div>
	{:else}
		<div class="flow-block">
			<div class="flow-status" aria-live="polite">
				<span class:active={isPlaying} class="signal" aria-hidden="true"></span>
				<div>
					<p class="eyebrow">
						{#if isStarting}
							Starting AI DJ
						{:else if isStopping}
							Stopping AI DJ
						{:else if isPlaybackBuffering}
							Buffering
						{:else if isPlaying}
							AI DJ is playing
						{:else if hasEnded}
							Session finished
						{:else if canControl}
							AI DJ is paused
						{:else if status === APP_STATES.STOPPED}
							Session stopped
						{:else}
							Waiting for a vibe
						{/if}
					</p>
					<p class="flow-line">{currentStep || 'Describe your vibe above.'}</p>
				</div>
			</div>

			{#if isChangingVibe}
				<p class="vibe-updating" aria-live="polite">
					<span class="spinner" aria-hidden="true"></span>
					New vibe accepted, processing — this track keeps playing until it's ready
				</p>
			{/if}

			<div class="deck-controls">
				<button
					class="segment-button"
					type="button"
					disabled={!canControl || !hasPrevious}
					aria-label="Previous segment"
					onclick={() => changeSegment(-1)}>⏮</button
				>
				<button
					class="play-button"
					type="button"
					onclick={onTogglePlay}
					disabled={!canControl || isStopping}
					aria-label={playLabel}
					aria-pressed={isPlaying}
				>
					{isPlaybackBuffering && playbackRequested ? '…' : isPlaying ? 'Ⅱ' : '▶'}
				</button>
				<button
					class="segment-button"
					type="button"
					disabled={!canControl || !hasNext}
					aria-label="Next segment"
					onclick={() => changeSegment(1)}>⏭</button
				>
				<button
					class="stop-button"
					type="button"
					onclick={handleStopClick}
					disabled={!canControl || isStopping}
				>
					{isStopping ? 'Stopping…' : 'Stop AI DJ'}
				</button>
			</div>

			<div class="progress-line">
				<span>{formatTime(currentTime)}</span>
				<input
					class="progress-slider"
					type="range"
					min="0"
					max="100"
					step="0.1"
					value={isStarting ? progress : progressPercent}
					oninput={handleSeekInput}
					disabled={!canControl || duration <= 0}
					aria-label="Seek audio position"
					aria-valuetext={`${formatTime(currentTime)} of ${formatTime(duration)}`}
				/>
				<span>{formatTime(duration)}</span>
			</div>

			{#if playbackError}
				<p class="playback-error" role="alert">{playbackError}</p>
			{/if}
		</div>
	{/if}

	{#if audioUrl}
		<audio
			class="hidden-audio"
			bind:this={audioElement}
			src={audioUrl}
			preload="metadata"
			onloadedmetadata={handleLoadedMetadata}
			ontimeupdate={syncTimeline}
			onplay={trackedMediaPlaying}
			onplaying={onMediaReady}
			onpause={trackedMediaPaused}
			onwaiting={onMediaWaiting}
			oncanplay={onMediaReady}
			onended={handleAudioEnded}
			onerror={handleMediaError}
		></audio>
	{/if}

	{#if preloadAudioUrl}
		<!-- Gives the browser a head start fetching the already-prepared next
		     track's bytes (design doc 4.3) -- not wired into playback at all,
		     just a hint; the real swap happens when advance()'s own result
		     replaces audioUrl above. -->
		<audio class="hidden-audio" src={preloadAudioUrl} preload="auto" aria-hidden="true"></audio>
	{/if}

	{#if !compact}
		<div class="coach-block">
			<p class="eyebrow">Coach the DJ</p>
			<div class="coach-row">
				{#each COACH_OPTIONS as option (option)}
					<button
						type="button"
						class:active={selectedFeedback === option}
						onclick={() => handleCoachFeedback(option)}
						disabled={!canControl || isFeedbackPending || isStopping}
						aria-pressed={selectedFeedback === option}
					>
						{pendingFeedback === option ? 'Sending…' : option}
					</button>
				{/each}
			</div>

			<label class="volume-control">
				<span aria-hidden="true">🔊</span>
				<span class="sr-only">Volume</span>
				<input type="range" min="0" max="100" value={volume} oninput={handleVolumeInput} />
				<span class="volume-value">{volume}%</span>
			</label>
			<p class="coach-note">Your feedback guides the next choice.</p>
		</div>
	{/if}
</section>

<style>
	.player-deck {
		position: fixed;
		left: 50%;
		bottom: 18px;
		z-index: 40;
		display: grid;
		grid-template-columns: minmax(220px, 330px) minmax(340px, 1fr) minmax(300px, 500px);
		gap: 26px;
		align-items: center;
		width: min(1500px, calc(100% - 32px));
		padding: 18px 24px;
		transform: translateX(-50%);
		border: 1px solid rgba(125, 183, 255, 0.3);
		border-radius: 24px;
		background: linear-gradient(180deg, rgba(8, 16, 31, 0.97), rgba(4, 9, 18, 0.97));
		box-shadow:
			0 22px 90px rgba(0, 0, 0, 0.62),
			0 0 70px rgba(59, 130, 246, 0.12);
		backdrop-filter: blur(18px);
		transition:
			bottom 0.15s ease-out,
			grid-template-columns 0.15s ease-out,
			padding 0.15s ease-out;
		/* On shorter viewports this fixed bar's own box can end up sitting over
		   page content behind it (Studio's dense panels in particular) -- only
		   its actual controls should capture clicks, not the empty space
		   around them, so anything under that space stays reachable. */
		pointer-events: none;
	}

	.player-deck :is(button, input, img) {
		pointer-events: auto;
	}

	/* MiniMixPlayer.svelte sits at bottom: 16px with roughly an 80px tall
	   bar -- clear it with a gap instead of overlapping directly. */
	.player-deck.stacked {
		bottom: 108px;
	}

	.player-deck.compact {
		grid-template-columns: minmax(180px, 1fr) auto;
		gap: 18px;
		padding: 10px 20px;
		border-radius: 18px;
	}

	.compact-toggle {
		position: absolute;
		top: -13px;
		right: 22px;
		display: grid;
		width: 26px;
		height: 26px;
		place-items: center;
		border: 1px solid rgba(125, 183, 255, 0.3);
		border-radius: 50%;
		background: #0b1729;
		color: var(--text-soft);
		font-size: 10px;
		line-height: 1;
	}

	.compact-toggle:hover {
		color: white;
		border-color: var(--accent-2);
	}

	.compact-controls {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 10px;
	}

	.track-block,
	.flow-status,
	.deck-controls,
	.progress-line,
	.coach-row {
		display: flex;
		align-items: center;
	}

	.track-block {
		min-width: 0;
		gap: 16px;
	}

	.cover {
		width: 70px;
		height: 70px;
		flex: 0 0 auto;
		border: 1px solid rgba(125, 183, 255, 0.25);
		border-radius: 14px;
		object-fit: cover;
	}

	.placeholder {
		display: grid;
		place-items: center;
		background: linear-gradient(135deg, #264984, #6ea9ff);
		color: white;
		font-weight: 900;
	}

	.compact .cover {
		width: 44px;
		height: 44px;
		border-radius: 10px;
	}

	.compact .track-copy h2 {
		font-size: 14px;
	}

	.compact .track-copy p {
		font-size: 12px;
	}

	.track-copy {
		min-width: 0;
	}

	.track-copy h2 {
		overflow: hidden;
		margin: 0 0 5px;
		color: var(--text-main);
		font-size: 18px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.track-copy p,
	.flow-line,
	.coach-note {
		margin: 0;
		color: var(--text-muted);
		font-size: 14px;
	}

	.flow-block,
	.coach-block {
		display: grid;
		gap: 12px;
	}

	.flow-status {
		gap: 12px;
	}

	.signal {
		width: 26px;
		height: 18px;
		background: repeating-linear-gradient(90deg, var(--accent-2) 0 2px, transparent 2px 6px);
		opacity: 0.45;
	}

	.signal.active {
		opacity: 1;
		animation: pulse 900ms ease-in-out infinite alternate;
	}

	.eyebrow {
		margin: 0 0 4px;
		color: var(--accent-2);
		font-size: 12px;
		font-weight: 900;
		letter-spacing: 0.14em;
		text-transform: uppercase;
	}

	.deck-controls {
		justify-content: center;
		gap: 14px;
	}

	.play-button,
	.segment-button {
		display: grid;
		place-items: center;
		border: 1px solid rgba(125, 183, 255, 0.28);
		border-radius: 999px;
	}

	.play-button {
		width: 62px;
		height: 62px;
		background: linear-gradient(135deg, #1f5edb, #74adff);
		box-shadow: var(--shadow-blue);
		color: white;
		font-size: 24px;
	}

	.segment-button {
		width: 44px;
		height: 44px;
		background: rgba(125, 183, 255, 0.06);
		color: var(--text-soft);
	}

	.play-button.small {
		width: 46px;
		height: 46px;
		font-size: 18px;
	}

	.compact .segment-button {
		width: 36px;
		height: 36px;
	}

	.stop-button,
	.coach-row button {
		border: 1px solid var(--border-soft);
		border-radius: 999px;
		padding: 10px 14px;
		background: rgba(125, 183, 255, 0.05);
		color: var(--text-soft);
		font-size: 13px;
		font-weight: 800;
	}

	.progress-line {
		gap: 12px;
		color: var(--text-muted);
		font-size: 13px;
	}

	.progress-slider {
		flex: 1;
		accent-color: var(--accent-2);
	}

	.playback-error {
		margin: 0;
		color: #ff9aab;
		font-size: 13px;
	}

	.vibe-updating {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0;
		color: var(--accent-2);
		font-size: 13px;
		font-weight: 700;
	}

	.spinner {
		display: inline-block;
		width: 12px;
		height: 12px;
		flex: 0 0 auto;
		border: 2px solid rgba(125, 183, 255, 0.25);
		border-top-color: var(--accent-2);
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}

	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation: none;
		}
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.hidden-audio {
		display: none;
	}

	.coach-row {
		flex-wrap: wrap;
		gap: 8px;
	}

	.coach-row button.active {
		border-color: var(--accent-2);
		background: rgba(59, 130, 246, 0.2);
		color: white;
	}

	.volume-control {
		display: grid;
		grid-template-columns: auto 1fr auto;
		gap: 10px;
		align-items: center;
		color: var(--text-soft);
		font-size: 13px;
	}

	.volume-control input {
		width: 100%;
		accent-color: var(--accent-2);
	}

	.volume-value {
		min-width: 38px;
		text-align: right;
	}

	button:disabled,
	input:disabled {
		cursor: not-allowed;
		opacity: 0.42;
	}

	@keyframes pulse {
		to {
			transform: scaleY(0.65);
		}
	}

	@media (max-width: 1180px) {
		.player-deck,
		.player-deck.compact {
			position: relative;
			grid-template-columns: 1fr;
			width: 100%;
			margin-top: 24px;
			transform: none;
		}

		.compact-controls {
			justify-content: flex-start;
		}
	}

	@media (max-width: 620px) {
		.player-deck {
			padding: 16px;
		}

		.deck-controls {
			flex-wrap: wrap;
		}

		.stop-button {
			flex-basis: 100%;
		}

		.coach-row button {
			flex: 1 1 42%;
		}
	}
</style>
