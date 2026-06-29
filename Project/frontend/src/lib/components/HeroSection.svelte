<script>
  /**
   * Purpose:
   * Main product explanation above the player.
   *
   * How this connects to the project:
   * The hero explains the current product direction: a prompt-based AI DJ that
   * keeps mixing the vibe until the user stops, not a fixed-duration export.
   *
   * Engineering decision:
   * Keep marketing text separate from the player/prompt components so copy can
   * be changed without touching application logic.
   */
</script>

<section class="hero">
  <span class="badge">Prompt-based AI DJ session</span>

  <h1>Tell the AI DJ your vibe.</h1>

  <p>
    The app keeps mixing the best song moments for that vibe until you stop.
    No timelines, no scores, just a clean AI music player.
  </p>
</section>

<style>
  .hero {
    text-align: center;
    max-width: 820px;
    margin: 56px auto 32px;
  }

  h1 {
    margin: 18px 0 16px;
    font-size: clamp(42px, 7vw, 76px);
    line-height: 0.95;
    letter-spacing: -0.06em;
  }

  p {
    margin: 0 auto;
    max-width: 680px;
    color: var(--text-muted);
    font-size: 18px;
    line-height: 1.7;
  }
</style>
