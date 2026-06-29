<script>
  /**
   * Purpose:
   * Optional explanation panel for demo/lecturer/developer use.
   *
   * How this connects to the project:
   * The normal user player hides raw ML details. This panel keeps explainability
   * available without making the main music experience feel like a dashboard.
   *
   * Engineering decision:
   * Explanations are written in human language. We do not show raw segment
   * scores, transition scores, or timestamps here unless we intentionally add a
   * developer mode later.
   *
   * @typedef {import("../types.js").DJSession} DJSession
   */

  /** @type {DJSession | null} */
  export let session = null;

  /** @type {boolean} */
  export let isOpen = false;

  /** @type {() => void} */
  export let onToggle = () => {};
</script>

{#if session}
  <section class="reasoning card">
    <button class="reasoning-toggle" on:click={onToggle}>
      {isOpen ? "Hide AI reasoning" : "Show AI reasoning"}
    </button>

    {#if isOpen}
      <div class="content">
        <div>
          <span>Why this song moment?</span>
          <p>{session.reasoning.selectedBecause}</p>
        </div>

        <div>
          <span>Transition plan</span>
          <p>{session.reasoning.transitionPlan}</p>
        </div>

        <div>
          <span>Where the vibe goes next</span>
          <p>{session.reasoning.nextDirection}</p>
        </div>
      </div>
    {/if}
  </section>
{/if}

<style>
  .reasoning {
    padding: 20px 24px;
    margin-bottom: 48px;
  }

  .reasoning-toggle {
    border: none;
    background: transparent;
    color: var(--accent-2);
    font-weight: 800;
  }

  .content {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
    margin-top: 18px;
  }

  .content div {
    border: 1px solid var(--border-soft);
    border-radius: 16px;
    padding: 14px;
    background: rgba(255, 255, 255, 0.06);
  }

  span {
    display: block;
    color: var(--accent-2);
    font-weight: 800;
    margin-bottom: 8px;
  }

  p {
    margin: 0;
    color: var(--text-muted);
    line-height: 1.6;
  }

  @media (max-width: 850px) {
    .content {
      grid-template-columns: 1fr;
    }
  }
</style>
