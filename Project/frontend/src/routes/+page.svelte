<!--
  File: src/routes/+page.svelte
  Purpose: Home route for the main guest AI DJ experience.
  What it does:
  - Renders the hero, prompt composer, current-vibe strip, errors, and bottom player.
  - Controls when the prompt is visible or hidden.
  - Shows the full prompt before starting, hides it while playing, and allows Change vibe to reopen it.
  - Passes store state and store actions down to components.
  Main flow:
  1. User writes/selects a vibe.
  2. User clicks Start AI DJ.
  3. Prompt hides and bottom player becomes active.
  4. User can coach the DJ or change the vibe.
  5. Stopping the session shows the prompt again.
-->

<script>
	/**
	 * Zonix home route.
	 *
	 * Behavior:
	 * - Before starting: show the full prompt composer.
	 * - After starting: hide the composer so the listening experience feels clean.
	 * - While playing: show a small "Change vibe" strip. Clicking it opens the
	 *   prompt composer as a compact overlay so the user can retune the session.
	 * - After stopping: show the full prompt composer again.
	 */

	import { APP_STATES } from '$lib/constants/appStates.js';
	import { sessionStore } from '$lib/stores/sessionStore.js';

	import HeroSection from '$lib/components/HeroSection.svelte';
	import PromptComposer from '$lib/components/PromptComposer.svelte';
	import DJPlayerCard from '$lib/components/DJPlayerCard.svelte';

	/* Local UI-only state:
     Tracks whether the compact prompt panel is currently open while a session is active.
     This is different from the global sessionStore because it only controls page layout. */
	let promptPanelOpen = $state(false);

	/* Derived state:
     true when the AI DJ is starting, playing, or preparing the next chunk.
     When this is true, the page should avoid showing the full prompt unless the user asked to change vibe. */
	let isSessionActive = $derived(
		$sessionStore.status === APP_STATES.PLAYING ||
			$sessionStore.status === APP_STATES.BUFFERING_NEXT ||
			$sessionStore.status === APP_STATES.STARTING
	);

	/* Derived state:
     true only when the session is already usable.
     This enables the small Current vibe strip and Change vibe button. */
	let canChangeVibe = $derived(
		$sessionStore.status === APP_STATES.PLAYING ||
			$sessionStore.status === APP_STATES.BUFFERING_NEXT
	);

	/* Derived state:
     Shows the prompt in two cases:
     1. no active session, so the user needs a starting point;
     2. active session + promptPanelOpen, so the user is editing the vibe. */
	let shouldShowPrompt = $derived(!isSessionActive || promptPanelOpen);

	/* Starts or updates the AI DJ session.
     The prompt panel closes immediately so the UI returns to listening mode. */
	async function startVibe() {
		promptPanelOpen = false;
		await sessionStore.start();
	}

	function openPromptPanel() {
		promptPanelOpen = true;
	}

	function closePromptPanel() {
		promptPanelOpen = false;
	}
</script>

<div class="home-stage">
	<HeroSection />

	{#if shouldShowPrompt}
		<div class={isSessionActive ? 'prompt-overlay' : ''}>
			<PromptComposer
				prompt={$sessionStore.prompt}
				isStarting={$sessionStore.status === APP_STATES.STARTING}
				isOverlay={isSessionActive}
				showCancel={isSessionActive}
				startLabel={isSessionActive ? 'Update vibe' : '▶ Start AI DJ'}
				onPromptChange={sessionStore.setPrompt}
				onStart={startVibe}
				onCancel={closePromptPanel}
			/>
		</div>
	{:else if canChangeVibe}
		<section class="active-vibe-strip card" aria-label="Current Zonix prompt">
			<div>
				<p class="eyebrow">Current vibe</p>
				<p class="prompt-preview">{$sessionStore.prompt}</p>
			</div>

			<button class="secondary-button" onclick={openPromptPanel}>Change vibe</button>
		</section>
	{/if}

	{#if $sessionStore.error}
		<section class="error-box card" role="alert" aria-live="assertive">
			<h3>{$sessionStore.status === APP_STATES.ERROR ? 'Signal interrupted' : 'Request failed'}</h3>
			<p>{$sessionStore.error}</p>
			{#if $sessionStore.status === APP_STATES.ERROR}
				<button class="secondary-button" type="button" onclick={sessionStore.reset}
					>Try again</button
				>
			{:else}
				<button class="secondary-button" type="button" onclick={sessionStore.clearError}
					>Dismiss</button
				>
			{/if}
		</section>
	{/if}
</div>

<DJPlayerCard
	status={$sessionStore.status}
	currentStep={$sessionStore.currentStep}
	progress={$sessionStore.progress}
	session={$sessionStore.session}
	isPlaying={$sessionStore.isPlaying}
	playbackRequested={$sessionStore.playbackRequested}
	isPlaybackBuffering={$sessionStore.isPlaybackBuffering}
	hasEnded={$sessionStore.hasEnded}
	isStopping={$sessionStore.isStopping}
	isFeedbackPending={$sessionStore.isFeedbackPending}
	pendingFeedback={$sessionStore.pendingFeedback}
	selectedFeedback={$sessionStore.selectedFeedback}
	playbackError={$sessionStore.playbackError}
	onTogglePlay={sessionStore.togglePlay}
	onStop={sessionStore.stop}
	onFeedback={sessionStore.sendFeedback}
	onMediaPlaying={sessionStore.mediaPlaying}
	onMediaPaused={sessionStore.mediaPaused}
	onMediaWaiting={sessionStore.mediaWaiting}
	onMediaReady={sessionStore.mediaReady}
	onMediaEnded={sessionStore.mediaEnded}
	onMediaError={sessionStore.mediaError}
/>

<style>
	.home-stage {
		width: min(1500px, 100%);
		margin: 0 auto;
	}

	.prompt-overlay {
		width: min(1080px, 100%);
		margin: -18px auto 30px;
		animation: promptIn 0.2s ease-out;
	}

	.active-vibe-strip {
		width: min(1080px, 100%);
		margin: -18px auto 30px;
		padding: 18px 22px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 18px;
	}

	.active-vibe-strip > * {
		position: relative;
		z-index: 1;
	}

	.eyebrow {
		margin: 0 0 5px;
		color: var(--accent-2);
		font-size: 12px;
		font-weight: 900;
		letter-spacing: 0.16em;
		text-transform: uppercase;
	}

	.prompt-preview {
		max-width: 760px;
		overflow: hidden;
		margin: 0;
		color: var(--text-soft);
		font-size: 15px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.error-box {
		width: min(900px, 100%);
		margin: 0 auto 24px;
		padding: 22px;
	}

	.error-box > * {
		position: relative;
		z-index: 1;
	}

	.error-box h3 {
		margin: 0 0 8px;
	}

	.error-box p {
		color: var(--text-muted);
	}

	@keyframes promptIn {
		from {
			transform: translateY(8px);
			opacity: 0;
		}

		to {
			transform: translateY(0);
			opacity: 1;
		}
	}

	@media (max-width: 760px) {
		.active-vibe-strip {
			align-items: stretch;
			flex-direction: column;
		}

		.prompt-preview {
			white-space: normal;
		}
	}
</style>
