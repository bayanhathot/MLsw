<script>
  /*
    Prompt composer.

    Lets the user write a vibe or choose a preset.
    Presets fill the prompt but do not start automatically.
  */

  import { PRESETS } from "$lib/constants/presets.js";

  /**
   * @typedef {import("$lib/types.js").Preset} Preset
   */

  /**
   * @type {{
   *   prompt?: string,
   *   isStarting?: boolean,
   *   onPromptChange?: (prompt: string) => void,
   *   onStart?: () => void
   * }}
   */
  let {
    prompt = "",
    isStarting = false,
    onPromptChange = () => {},
    onStart = () => {}
  } = $props();

  /**
 * Handles textarea input.
 *
 * Svelte passes a normal Event here, so we cast currentTarget
 * to HTMLTextAreaElement before reading value.
 *
 * @param {Event} event
 */
function handlePromptInput(event) {
  const target = /** @type {HTMLTextAreaElement} */ (event.currentTarget);
  onPromptChange(target.value);
}

  /**
   * @param {Preset} preset
   */
  function usePreset(preset) {
    onPromptChange(preset.prompt);
  }
</script>

<section class="composer card">
  <div class="composer-header">
    <div>
      <p class="eyebrow">Describe your vibe</p>
      <h2>What should the AI DJ play?</h2>
    </div>

    <button
      class="primary-button"
      onclick={onStart}
      disabled={isStarting || !prompt.trim()}
    >
      {isStarting ? "Starting..." : "Start AI DJ"}
    </button>
  </div>

  <textarea
    value={prompt}
    oninput={handlePromptInput}
    placeholder="Example: late night emotional Arabic classics with smooth transitions and warm vocals"
  ></textarea>

  <div class="preset-row">
    {#each PRESETS as preset}
      <button class="preset-chip" onclick={() => usePreset(preset)}>
        {preset.label}
      </button>
    {/each}
  </div>
</section>

<style>
  .composer {
    padding: 28px;
    margin-bottom: 28px;
  }

  .composer-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 20px;
    margin-bottom: 18px;
  }

  .eyebrow {
    color: var(--accent-2);
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  h2 {
    margin: 6px 0 0;
    font-size: 30px;
  }

  textarea {
    width: 100%;
    min-height: 120px;
    resize: vertical;
    border: 1px solid var(--border-soft);
    border-radius: 20px;
    padding: 18px;
    color: var(--text-main);
    background: rgba(255, 255, 255, 0.08);
    outline: none;
    font: inherit;
  }

  textarea::placeholder {
    color: var(--text-muted);
  }

  .preset-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 18px;
  }

  .preset-chip {
    border: 1px solid var(--border-soft);
    border-radius: 999px;
    padding: 10px 14px;
    color: var(--text-main);
    background: rgba(255, 255, 255, 0.06);
    cursor: pointer;
  }

  .preset-chip:hover {
    border-color: var(--accent-2);
  }

  @media (max-width: 720px) {
    .composer-header {
      flex-direction: column;
    }

    .composer-header button {
      width: 100%;
    }
  }
</style>