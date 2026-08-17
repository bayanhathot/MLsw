<!--
  File: src/routes/+layout.svelte
  Purpose: Root SvelteKit layout shared by all pages.
  What it does:
  - Imports global CSS once for the whole app.
  - Renders the Navbar above every route.
  - Provides the main centered app shell width.
  - Uses Svelte 5 {@render children()} to display the active route page.
  - Renders DJPlayerCard here (not on routes/+page.svelte) so the live AI
    DJ session -- and its <audio> element -- survives SPA navigation
    instead of being destroyed and recreated on every route change.
    sessionStore is itself a module-level singleton, so the session state
    behind it was already surviving navigation; only the player UI/audio
    element previously lived inside the home route.
  Why this file exists:
  - In SvelteKit, +layout.svelte replaces the old Vite App.svelte outer shell.
-->

<script>
	import { onMount } from 'svelte';

	import '../app.css';
	import Navbar from '$lib/components/Navbar.svelte';
	import GlobalPlayer from '$lib/components/GlobalPlayer.svelte';
	import DJPlayerCard from '$lib/components/DJPlayerCard.svelte';
	import { authStore } from '$lib/stores/authStore.js';
	import { sessionStore } from '$lib/stores/sessionStore.js';

	let { children } = $props();

	onMount(() => {
		authStore.checkAuth();
	});
</script>

<div class="app-shell">
	<Navbar />

	{@render children()}

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
		isChangingVibe={$sessionStore.isChangingVibe}
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
		onPrepareNext={sessionStore.prepareNext}
	/>
	<GlobalPlayer />
</div>

<style>
	.app-shell {
		width: min(1500px, calc(100% - 32px));
		margin: 0 auto;
	}
</style>
