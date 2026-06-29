<script>
  /*
    Zonix feedback controls.

    The buttons use brand language instead of ML terms. The user guides the
    feeling of the next moments without seeing raw model scores.
  */

  const FEEDBACK_OPTIONS = [
    "Good vibe",
    "More energy",
    "Less vocals",
    "Smoother",
    "More focus",
    "Change energy"
  ];

  /**
   * @type {{
   *   selectedFeedback?: string | null,
   *   onFeedback?: (feedback: string) => void
   * }}
   */
  let {
    selectedFeedback = null,
    onFeedback = () => {}
  } = $props();
</script>

<section class="feedback card">
  <div>
    <p class="eyebrow">Guide the AI DJ</p>
    <h3>Shape the next moments.</h3>
  </div>

  <div class="feedback-row">
    {#each FEEDBACK_OPTIONS as option}
      <button
        class:active={selectedFeedback === option}
        onclick={() => onFeedback(option)}
      >
        {option}
      </button>
    {/each}
  </div>
</section>

<style>
  .feedback {
    display: grid;
    gap: 18px;
    padding: 24px;
    margin-bottom: 24px;
  }

  .feedback > * {
    position: relative;
    z-index: 1;
  }

  .eyebrow {
    color: var(--accent-2);
    font-size: 12px;
    font-weight: 1000;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }

  h3 {
    margin: 6px 0 0;
    font-size: 24px;
    letter-spacing: -0.035em;
  }

  .feedback-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }

  button {
    border: 1px solid var(--border-muted);
    border-radius: 999px;
    padding: 10px 14px;
    color: var(--text-main);
    background: rgba(255, 255, 255, 0.035);
    cursor: pointer;
    font-size: 13px;
    font-weight: 900;
  }

  button.active,
  button:hover {
    border-color: var(--accent);
    color: #001015;
    background: var(--accent);
    box-shadow: var(--shadow-cyan);
  }
</style>
