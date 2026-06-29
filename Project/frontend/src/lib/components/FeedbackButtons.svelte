<script>
  /*
    Simple user feedback.

    The user should not need to understand ML scores.
    These buttons describe musical preference changes.
  */

  const FEEDBACK_OPTIONS = [
    "Good vibe",
    "More energy",
    "Less vocals",
    "Smoother",
    "Surprise me",
    "Stop this style"
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
    <p class="eyebrow">Guide the DJ</p>
    <h3>How should the next moments feel?</h3>
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

  .eyebrow {
    color: var(--accent-2);
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  h3 {
    margin: 6px 0 0;
    font-size: 24px;
  }

  .feedback-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }

  button {
    border: 1px solid var(--border-soft);
    border-radius: 999px;
    padding: 10px 14px;
    color: var(--text-main);
    background: rgba(255, 255, 255, 0.06);
    cursor: pointer;
  }

  button.active,
  button:hover {
    border-color: var(--accent-2);
    background: rgba(125, 211, 252, 0.14);
  }
</style>