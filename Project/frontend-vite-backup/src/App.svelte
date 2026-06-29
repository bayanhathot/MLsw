<script>
  import { APP_STATES } from "./lib/constants/appStates.js";
  import { sessionStore } from "./lib/stores/sessionStore.js";

  import Navbar from "./lib/components/Navbar.svelte";
  import HeroSection from "./lib/components/HeroSection.svelte";
  import PromptComposer from "./lib/components/PromptComposer.svelte";
  import DJPlayerCard from "./lib/components/DJPlayerCard.svelte";
  import FeedbackButtons from "./lib/components/FeedbackButtons.svelte";
  import AIReasoningPanel from "./lib/components/AIReasoningPanel.svelte";

  /**
   * Purpose:
   * Root page composition for the Smart AI DJ frontend.
   *
   * How this connects to the project:
   * This file decides which major sections appear on the homepage: navbar, hero,
   * prompt input, main AI DJ player, feedback, and optional reasoning.
   *
   * Engineering decisions:
   * - App.svelte does not contain business logic. It reads state from sessionStore.
   * - Feedback is shown only while actively playing, not after the session stops.
   * - AI reasoning may still be opened after stopping, because it is useful for demos.
   */

  $: canStartNewSession =
    $sessionStore.status === APP_STATES.IDLE ||
    $sessionStore.status === APP_STATES.STOPPED ||
    $sessionStore.status === APP_STATES.ERROR;

  $: isActiveSession =
    $sessionStore.status === APP_STATES.PLAYING ||
    $sessionStore.status === APP_STATES.BUFFERING_NEXT;

  $: canShowReasoning =
    ($sessionStore.status === APP_STATES.PLAYING ||
      $sessionStore.status === APP_STATES.BUFFERING_NEXT ||
      $sessionStore.status === APP_STATES.STOPPED) &&
    $sessionStore.session;
</script>

<div class="app-shell">
  <Navbar />
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

  {#if canStartNewSession}
    <PromptComposer
      prompt={$sessionStore.prompt}
      isStarting={$sessionStore.status === APP_STATES.STARTING}
      onPromptChange={sessionStore.setPrompt}
      onStart={sessionStore.start}
    />
  {/if}

  {#if $sessionStore.status === APP_STATES.ERROR}
    <section class="error-box card">
      <h3>Something went wrong</h3>
      <p>{$sessionStore.error}</p>
      <button class="secondary-button" on:click={sessionStore.reset}>Try again</button>
    </section>
  {/if}

  {#if isActiveSession}
    <FeedbackButtons
      selectedFeedback={$sessionStore.selectedFeedback}
      onFeedback={sessionStore.sendFeedback}
    />
  {/if}

  {#if canShowReasoning}
    <AIReasoningPanel
      session={$sessionStore.session}
      isOpen={$sessionStore.showReasoning}
      onToggle={sessionStore.toggleReasoning}
    />
  {/if}
</div>

<style>
  .app-shell {
    width: min(1180px, calc(100% - 32px));
    margin: 0 auto;
  }

  .error-box {
    padding: 24px;
    margin-bottom: 24px;
  }

  .error-box p {
    color: var(--text-muted);
  }
</style>
