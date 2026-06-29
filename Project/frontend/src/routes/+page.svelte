<script>
  /*
    Home page route: /

    Final MVP behavior:
    - Before playing: show prompt composer.
    - While playing: hide prompt composer and show feedback controls.
    - AI reasoning is removed from the main UI.
  */

  import { APP_STATES } from "$lib/constants/appStates.js";
  import { sessionStore } from "$lib/stores/sessionStore.js";

  import HeroSection from "$lib/components/HeroSection.svelte";
  import DJPlayerCard from "$lib/components/DJPlayerCard.svelte";
  import PromptComposer from "$lib/components/PromptComposer.svelte";
  import FeedbackButtons from "$lib/components/FeedbackButtons.svelte";
</script>

<HeroSection />

<DJPlayerCard
  status={$sessionStore.status}
  currentStep={$sessionStore.currentStep}
  progress={$sessionStore.progress}
  session={$sessionStore.session}
  isPlaying={$sessionStore.isPlaying}
  onTogglePlay={sessionStore.togglePlay}
  onStop={sessionStore.stop}
/>

{#if $sessionStore.status !== APP_STATES.PLAYING}
  <PromptComposer
    prompt={$sessionStore.prompt}
    isStarting={$sessionStore.status === APP_STATES.STARTING}
    onPromptChange={sessionStore.setPrompt}
    onStart={sessionStore.start}
  />
{/if}

{#if $sessionStore.status === APP_STATES.PLAYING}
  <FeedbackButtons
    selectedFeedback={$sessionStore.selectedFeedback}
    onFeedback={sessionStore.sendFeedback}
  />
{/if}

{#if $sessionStore.status === APP_STATES.ERROR}
  <section class="error-box card">
    <h3>Something went wrong</h3>
    <p>{$sessionStore.error}</p>
    <button class="secondary-button" onclick={sessionStore.reset}>
      Try again
    </button>
  </section>
{/if}

<style>
  .error-box {
    padding: 24px;
    margin-bottom: 24px;
  }

  .error-box p {
    color: var(--text-muted);
  }
</style>