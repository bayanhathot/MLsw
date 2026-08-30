<script>
	import { onDestroy } from 'svelte';
	import { authStore } from '$lib/stores/authStore.js';
	import { getPlaybackManifest } from '$lib/services/mixApi.js';
	import { recordListeningEvent } from '$lib/services/listeningApi.js';

	/** @type {{ mix: import('$lib/types.js').Mix, onClose?: () => void }} */
	let { mix, onClose = () => {} } = $props();

	let manifest = $state(/** @type {import('$lib/types.js').PlaybackManifest | null} */ (null));
	let loadStatus = $state(/** @type {'loading'|'ready'|'error'} */ ('loading'));
	let loadError = $state('');

	let index = $state(0);
	let shouldPlay = $state(true);
	let isPlaying = $state(false);
	let currentTime = $state(0);
	let notice = $state('');
	/** @type {HTMLAudioElement | null} */
	let audioA = $state(null);
	/** @type {HTMLAudioElement | null} */
	let audioB = $state(null);
	// Which of the two alternating <audio> elements is currently the
	// foreground (audible, tracked) one -- the other is used to preload/
	// crossfade into the next segment. Two real elements rather than one
	// with a swapped src: Web Audio's AudioContext.createMediaElementSource
	// requires the *same-origin* CORS behavior Audius' stream endpoint does
	// not reliably provide (no Access-Control-Allow-Origin guarantee for
	// arbitrary third-party players), so a Web Audio crossfade graph would
	// silently fail cross-origin; alternating plain <audio> elements with
	// their own .volume ramps works regardless of CORS headers.
	let activeIsA = $state(true);
	/** @type {number | null} */
	let crossfadeRaf = null;
	/** @type {ReturnType<typeof setTimeout> | null} */
	let advanceTimer = null;

	let allSegments = $derived(manifest?.segments || []);
	let segment = $derived(allSegments[index] || null);
	let hasPrevious = $derived(index > 0);
	let hasNext = $derived(index < allSegments.length - 1);
	let allUnavailable = $derived(
		allSegments.length > 0 && allSegments.every((item) => item.availability !== 'available')
	);

	let trackingEventId = '';
	let trackingSegmentPosition = 0;
	let trackingStartedAt = /** @type {Date | null} */ (null);
	let listenedSeconds = 0;
	let eventFlushed = false;

	$effect(() => {
		const mixId = mix.id;
		void loadManifest(mixId);
		return () => {
			cleanupPlayback();
		};
	});

	/** @param {number} mixId */
	async function loadManifest(mixId) {
		loadStatus = 'loading';
		loadError = '';
		manifest = null;
		try {
			const loaded = await getPlaybackManifest(mixId);
			manifest = loaded;
			loadStatus = 'ready';
			index = loaded.segments.findIndex((item) => item.availability === 'available');
			if (index < 0) index = 0;
			// Called directly here (not from a reactive $effect keyed on
			// `manifest`/`loadStatus`): playCurrent() itself reads `segment`/
			// `index`, which change on every subsequent advance -- a broad
			// $effect would auto-track those too and re-fire on every
			// segment change, restarting playback out from under the
			// transition logic that just ran. Calling it once, right here,
			// is the only "on initial load" trigger this needs.
			playCurrent();
		} catch (requestError) {
			loadStatus = 'error';
			loadError = requestError instanceof Error ? requestError.message : 'Could not load this mix.';
		}
	}

	function foregroundElement() {
		return activeIsA ? audioA : audioB;
	}

	function backgroundElement() {
		return activeIsA ? audioB : audioA;
	}

	function makeEventId() {
		return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
			? `listen:${crypto.randomUUID()}`
			: `listen:${Date.now()}:${Math.random().toString(36).slice(2)}`;
	}

	function resetTracking() {
		trackingEventId = makeEventId();
		trackingSegmentPosition = segment?.position || 0;
		trackingStartedAt = null;
		listenedSeconds = 0;
		eventFlushed = false;
	}

	/** @param {boolean} skipped @param {boolean} [keepalive] */
	async function flushListening(skipped, keepalive = false) {
		const observedSeconds = Math.max(listenedSeconds, currentTime);
		if (
			eventFlushed ||
			$authStore.status !== 'authenticated' ||
			!trackingSegmentPosition ||
			!trackingStartedAt ||
			observedSeconds < 0.75
		) {
			return;
		}
		eventFlushed = true;
		try {
			await recordListeningEvent({
				clientEventId: trackingEventId,
				mixId: mix.id,
				segmentId: trackingSegmentPosition,
				startedAt: trackingStartedAt.toISOString(),
				endedAt: new Date().toISOString(),
				secondsListened: observedSeconds,
				skipped,
				keepalive
			});
		} catch (requestError) {
			console.warn('Cuemix listening event was not recorded.', requestError);
		}
	}

	/** @param {number} seconds */
	function formatTime(seconds) {
		if (!Number.isFinite(seconds) || seconds <= 0) return '0:00';
		return `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60)
			.toString()
			.padStart(2, '0')}`;
	}

	function clearCrossfadeTimers() {
		if (crossfadeRaf !== null) {
			cancelAnimationFrame(crossfadeRaf);
			crossfadeRaf = null;
		}
		if (advanceTimer !== null) {
			clearTimeout(advanceTimer);
			advanceTimer = null;
		}
	}

	function cleanupPlayback() {
		clearCrossfadeTimers();
		void flushListening(true, true);
		for (const element of [audioA, audioB]) {
			if (!element) continue;
			element.pause();
			element.removeAttribute('src');
			element.load();
		}
	}

	/** @param {HTMLAudioElement | null} element @param {import('$lib/types.js').PlaybackManifestSegment} item */
	function cueElement(element, item) {
		if (!element || !item.audioUrl) return;
		if (element.src !== item.audioUrl) {
			element.src = item.audioUrl;
		}
		element.currentTime = Math.max(0, item.startMs / 1000);
	}

	function preloadNext() {
		if (!hasNext) return;
		const next = allSegments[index + 1];
		if (!next || next.availability !== 'available' || !next.audioUrl) return;
		const bg = backgroundElement();
		if (!bg) return;
		bg.volume = next.transitionType === 'crossfade' ? 0 : 1;
		cueElement(bg, next);
	}

	function playCurrent() {
		if (!segment || segment.availability !== 'available' || !segment.audioUrl) {
			notice = segment ? `"${segment.title}" is unavailable and was skipped.` : '';
			skipUnavailable();
			return;
		}
		const fg = foregroundElement();
		if (!fg) return;
		cueElement(fg, segment);
		fg.volume = 1;
		resetTracking();
		if (shouldPlay) {
			fg.play().catch(() => {
				shouldPlay = false;
				notice = 'Press play to start this mix.';
			});
		}
		preloadNext();
	}

	function skipUnavailable() {
		if (hasNext) {
			void flushListening(true);
			index += 1;
			currentTime = 0;
			playCurrent();
		} else {
			shouldPlay = false;
			isPlaying = false;
		}
	}

	function handleTimeUpdate() {
		const fg = foregroundElement();
		if (!fg || !segment) return;
		const nowMs = fg.currentTime * 1000;
		currentTime = Math.max(0, (nowMs - segment.startMs) / 1000);
		if (isPlaying) listenedSeconds = Math.max(listenedSeconds, currentTime);

		const endMs = segment.endMs;
		const transitionMs = segment.transitionType === 'crossfade' ? segment.transitionDurationMs : 0;
		const crossfadeStartMs = endMs - transitionMs;

		if (transitionMs > 0 && hasNext && nowMs >= crossfadeStartMs && nowMs < endMs) {
			runCrossfade(fg, endMs);
		} else if (nowMs >= endMs) {
			advanceToNext();
		}
	}

	let crossfading = false;

	/** @param {HTMLAudioElement} outgoing @param {number} endMs */
	function runCrossfade(outgoing, endMs) {
		if (crossfading) return;
		const next = allSegments[index + 1];
		const bg = backgroundElement();
		if (!next || !bg || next.availability !== 'available' || !next.audioUrl) return;
		crossfading = true;
		if (bg.paused) {
			bg.volume = 0;
			bg.play().catch(() => {});
		}
		const remainingMs = Math.max(1, endMs - outgoing.currentTime * 1000);
		const step = () => {
			const ratio = Math.min(1, 1 - Math.max(0, endMs - outgoing.currentTime * 1000) / remainingMs);
			outgoing.volume = Math.max(0, 1 - ratio);
			bg.volume = Math.min(1, ratio);
			if (ratio >= 1 || outgoing.currentTime * 1000 >= endMs) {
				advanceToNext();
				return;
			}
			crossfadeRaf = requestAnimationFrame(step);
		};
		crossfadeRaf = requestAnimationFrame(step);
	}

	function advanceToNext() {
		clearCrossfadeTimers();
		crossfading = false;
		void flushListening(false);
		const outgoing = foregroundElement();
		if (outgoing) outgoing.pause();
		if (!hasNext) {
			shouldPlay = false;
			isPlaying = false;
			return;
		}
		index += 1;
		activeIsA = !activeIsA;
		const fg = foregroundElement();
		if (fg) fg.volume = 1;
		resetTracking();
		preloadNext();
		if (!shouldPlay) {
			const bg = backgroundElement();
			if (bg) bg.pause();
		}
	}

	function togglePlay() {
		if (!segment) return;
		shouldPlay = !shouldPlay;
		notice = '';
		const fg = foregroundElement();
		if (!fg) return;
		if (shouldPlay) {
			if (!fg.src) playCurrent();
			else fg.play().catch(() => (shouldPlay = false));
		} else {
			fg.pause();
		}
	}

	/** @param {number} nextIndex */
	function goTo(nextIndex) {
		if (nextIndex < 0 || nextIndex >= allSegments.length) return;
		void flushListening(true);
		clearCrossfadeTimers();
		crossfading = false;
		for (const element of [audioA, audioB]) element?.pause();
		index = nextIndex;
		currentTime = 0;
		notice = '';
		playCurrent();
	}

	function mediaPlaying() {
		isPlaying = true;
		notice = '';
		if (!trackingStartedAt) trackingStartedAt = new Date();
	}

	function mediaPaused() {
		if (foregroundElement()?.currentTime) isPlaying = false;
	}

	function mediaError() {
		notice = segment
			? `"${segment.title}" could not be played and was skipped.`
			: 'Playback error.';
		skipUnavailable();
	}

	function closePlayer() {
		cleanupPlayback();
		onClose();
	}

	onDestroy(() => {
		cleanupPlayback();
	});
</script>

<aside class="mini-player" aria-label="Mix player">
	<div class="art" style={`background-image: url('${segment?.coverUrl || ''}')`} aria-hidden="true">
		{#if !segment?.coverUrl}<span>ZX</span>{/if}
	</div>
	<div class="details">
		<span
			>Now playing (via {segment?.source
				? segment.source[0].toUpperCase() + segment.source.slice(1)
				: 'provider'}) · {allSegments.length ? index + 1 : 0}/{allSegments.length}</span
		>
		<strong>{manifest?.title || mix.title}</strong>
		<small>{segment?.title || ''} — {segment?.artist || ''}</small>
		{#if segment?.attribution}
			<small class="attribution">
				{segment.attribution}
				{#if segment.providerUrl}
					<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
					<a href={segment.providerUrl} target="_blank" rel="noreferrer noopener"
						>Open original track</a
					>
				{/if}
			</small>
		{/if}
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
		<progress
			value={currentTime}
			max={segment ? Math.max(0.01, (segment.endMs - segment.startMs) / 1000) : 1}
		></progress>
	</div>
	<button class="close" type="button" aria-label="Close mix player" onclick={closePlayer}
		>Close</button
	>
	{#if loadStatus === 'loading'}
		<p role="status">Loading playback…</p>
	{:else if loadStatus === 'error'}
		<p role="alert">{loadError}</p>
	{:else if allUnavailable}
		<p role="alert">Every track in this mix is currently unavailable from its provider.</p>
	{:else if notice}
		<p role="status">{notice}</p>
	{/if}
	<audio
		bind:this={audioA}
		class="audio"
		preload="auto"
		ontimeupdate={activeIsA ? handleTimeUpdate : null}
		onplay={activeIsA ? mediaPlaying : null}
		onpause={activeIsA ? mediaPaused : null}
		onerror={activeIsA ? mediaError : null}
	></audio>
	<audio
		bind:this={audioB}
		class="audio"
		preload="auto"
		ontimeupdate={!activeIsA ? handleTimeUpdate : null}
		onplay={!activeIsA ? mediaPlaying : null}
		onpause={!activeIsA ? mediaPaused : null}
		onerror={!activeIsA ? mediaError : null}
	></audio>
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
		gap: 1px;
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
	.details small.attribution {
		color: #8fb6ed;
		font-size: 11px;
	}
	.details small.attribution a {
		margin-left: 6px;
		color: #7d9cff;
		text-decoration: underline;
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
	button:focus-visible {
		outline: 2px solid var(--accent-2, #7d9cff);
		outline-offset: 2px;
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
	p[role='status'] {
		color: #8fb6ed;
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
