<!--
  File: src/lib/components/EqualizerBars.svelte

  Purpose:
  Small animated equalizer glyph - three bars bouncing out of phase,
  like a real audio meter. Idle (opacity-dimmed, still) when nothing is
  playing, alive when it is. Reused anywhere the app wants to say
  "audio is actually happening right now" (DJPlayerCard, PostCard).
-->

<script>
  /**
   * @type {{ active?: boolean, size?: "sm" | "md" }}
   */
  let { active = false, size = "md" } = $props();
</script>

<span class="equalizer" class:active data-size={size} aria-hidden="true">
  <span class="bar"></span>
  <span class="bar"></span>
  <span class="bar"></span>
</span>

<style>
  .equalizer {
    display: inline-flex;
    align-items: flex-end;
    gap: 3px;
    height: 16px;
    flex: 0 0 auto;
  }

  .equalizer[data-size="sm"] {
    height: 12px;
  }

  .bar {
    width: 3px;
    height: 30%;
    border-radius: 2px;
    background: var(--accent-2);
    opacity: 0.45;
  }

  .equalizer.active .bar {
    opacity: 1;
    animation: eq-bounce 1s ease-in-out infinite;
  }

  .equalizer.active .bar:nth-child(1) {
    animation-delay: -0.65s;
    animation-duration: 0.8s;
  }

  .equalizer.active .bar:nth-child(2) {
    animation-delay: -0.2s;
    animation-duration: 1.15s;
  }

  .equalizer.active .bar:nth-child(3) {
    animation-delay: -0.9s;
    animation-duration: 0.95s;
  }

  @keyframes eq-bounce {
    0%,
    100% {
      height: 25%;
    }
    50% {
      height: 100%;
    }
  }
</style>
