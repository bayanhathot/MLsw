<script>
  import { PRESETS } from "../constants/presets.js";

  /**
   * Purpose:
   * Prompt input and preset chip area.
   *
   * How this connects to the project:
   * This is where the user tells the AI DJ what vibe they want. It replaces the
   * old duration-based generator form with a simpler "Start AI DJ" flow.
   *
   * Engineering decisions:
   * - Presets fill the prompt instead of starting automatically, so users can edit.
   * - There is no duration selector because the session continues until stopped.
   * - Callback props keep this component visual; state changes happen in the store.
   *
   * @typedef {import("../types.js").Preset} Preset
   */

  /** @type {string} */
  export let prompt = "";

  /** @type {boolean} */
  export let isStarting = false;

  /** @type {(prompt: string) => void} */
  export let onPromptChange = () => {};

  /** @type {() => void} */
  export let onStart = () => {};

  /**
   * Inserts a preset prompt into the prompt box.
   *
   * @param {Preset} preset
   */
  function usePreset(preset) {
    onPromptChange(preset.prompt);
  }

  /**
   * Reads textarea value safely from the DOM event.
   *
   * @param {Event} event
   */
  function handlePromptInput(event) {
    const target = /** @type {HTMLTextAreaElement} */ (event.currentTarget);
    onPromptChange(target.value);
  }
</script>

<section class="composer card">
  <label for="prompt">Describe the vibe you want</label>

  <textarea
    id="prompt"
    value={prompt}
    on:input={handlePromptInput}
    placeholder="Example: Start an emotional tarab vibe with strong vocal peaks..."
  ></textarea>

  <div class="actions">
    <button
      class="primary-button"
      on:click={onStart}
      disabled={isStarting || prompt.trim() === ""}
    >
      {isStarting ? "Starting..." : "Start AI DJ"}
    </button>
  </div>

  <div class="presets" aria-label="Quick vibe presets">
    {#each PRESETS as preset}
      <button class="chip" on:click={() => usePreset(preset)}>
        {preset.label}
      </button>
    {/each}
  </div>
</section>

<style>
  .composer {
    padding: 24px;
    margin-bottom: 24px;
  }

  label {
    display: block;
    margin-bottom: 12px;
    font-weight: 800;
  }

  textarea {
    width: 100%;
    min-height: 118px;
    resize: vertical;
    border: 1px solid var(--border-soft);
    border-radius: 20px;
    background: rgba(255, 255, 255, 0.08);
    color: var(--text-main);
    padding: 16px;
    outline: none;
  }

  textarea::placeholder {
    color: var(--text-muted);
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 14px;
  }

  .presets {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 18px;
  }

  .chip {
    border: 1px solid var(--border-soft);
    border-radius: var(--radius-sm);
    padding: 9px 13px;
    color: var(--text-main);
    background: rgba(255, 255, 255, 0.07);
  }

  .chip:hover {
    background: rgba(255, 255, 255, 0.14);
  }

  @media (max-width: 600px) {
    .actions {
      justify-content: stretch;
    }

    .primary-button {
      width: 100%;
    }
  }
</style>
