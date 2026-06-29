<script>
  /**
   * Purpose:
   * Shows simple music-feeling feedback buttons.
   *
   * How this connects to the project:
   * In the future, these clicks become personalization signals. For example,
   * "More energy" can affect the next generated chunk/segment selection.
   *
   * Engineering decision:
   * Feedback uses user-language, not ML-language. We avoid technical feedback
   * like "bad graph edge" because normal users should not think about internals.
   */

  /** @type {string | null} */
  export let selectedFeedback = null;

  /** @type {(feedback: string) => void} */
  export let onFeedback = () => {};

  const options = [
    "Good vibe",
    "More energy",
    "Less vocals",
    "Smoother",
    "Surprise me",
    "Stop this style"
  ];
</script>

<section class="feedback card">
  <h3>Guide the AI DJ</h3>
  <p>These controls will later adjust the next song moments the AI DJ chooses.</p>

  <div class="buttons">
    {#each options as option}
      <button
        class:active={selectedFeedback === option}
        class="secondary-button"
        on:click={() => onFeedback(option)}
      >
        {option}
      </button>
    {/each}
  </div>
</section>

<style>
  .feedback {
    padding: 24px;
    margin-bottom: 24px;
  }

  h3 {
    margin: 0 0 8px;
  }

  p {
    margin: 0 0 16px;
    color: var(--text-muted);
  }

  .buttons {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }

  .active {
    border-color: rgba(56, 189, 248, 0.8);
    background: rgba(56, 189, 248, 0.16);
  }
</style>
