<!--
  File: src/lib/components/PostComposer.svelte
  Purpose: Compose a new feed post - a vibe prompt (used to generate the mix)
  plus a short description shown to friends.
-->

<script>
  import { PRESETS } from "$lib/constants/presets.js";

  /**
   * @type {{
   *   isPosting?: boolean,
   *   onSubmit?: (params: { prompt: string, description: string }) => Promise<void>
   * }}
   */
  let { isPosting = false, onSubmit = async () => {} } = $props();

  let prompt = $state("");
  let description = $state("");
  let error = $state("");

  /**
   * @param {import("$lib/types.js").Preset} preset
   */
  function usePreset(preset) {
    prompt = preset.prompt;
  }

  /**
   * @param {SubmitEvent} event
   */
  async function handleSubmit(event) {
    event.preventDefault();

    error = "";

    if (!prompt.trim() || !description.trim()) {
      error = "Describe the vibe and add a short description before posting.";
      return;
    }

    try {
      await onSubmit({ prompt: prompt.trim(), description: description.trim() });
      prompt = "";
      description = "";
    } catch (err) {
      error = err instanceof Error ? err.message : "Failed to create the post.";
    }
  }
</script>

<section class="composer card">
  <p class="eyebrow">Share a mix</p>

  <form onsubmit={handleSubmit}>
    <label for="post-prompt">Describe the vibe</label>
    <input
      id="post-prompt"
      bind:value={prompt}
      type="text"
      placeholder="e.g. emotional Arabic vocals with smooth transitions"
    />

    <div class="shortcut-row" aria-label="Quick vibe shortcuts">
      {#each PRESETS.slice(0, 5) as preset}
        <button type="button" class="preset-chip" onclick={() => usePreset(preset)}>
          {preset.label}
        </button>
      {/each}
    </div>

    <label for="post-description">Add a description</label>
    <input
      id="post-description"
      bind:value={description}
      type="text"
      maxlength="500"
      placeholder="What's this mix for?"
    />

    {#if error}
      <p class="error">{error}</p>
    {/if}

    <button class="primary-button" type="submit" disabled={isPosting}>
      {isPosting ? "Building your mix..." : "Post to feed"}
    </button>
  </form>
</section>

<style>
  .composer {
    padding: 22px 24px;
  }

  .eyebrow {
    margin: 0 0 14px;
    color: var(--accent-2);
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }

  form {
    display: grid;
    gap: 8px;
  }

  label {
    color: var(--text-soft);
    font-weight: 800;
    font-size: 13px;
    margin-top: 6px;
  }

  input {
    width: 100%;
    min-height: 48px;
    border: 1px solid var(--border-muted);
    border-radius: 14px;
    padding: 0 16px;
    color: var(--text-main);
    background: rgba(0, 0, 0, 0.22);
    outline: none;
  }

  input:focus {
    border-color: rgba(125, 183, 255, 0.42);
  }

  .shortcut-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 2px 0 4px;
  }

  .preset-chip {
    border: 1px solid var(--border-muted);
    border-radius: 999px;
    padding: 8px 14px;
    color: var(--text-soft);
    background: rgba(255, 255, 255, 0.025);
    font-size: 13px;
  }

  .preset-chip:hover {
    border-color: var(--accent-2);
    color: var(--text-main);
    background: rgba(125, 183, 255, 0.08);
  }

  .error {
    margin: 0;
    color: var(--danger);
  }

  button[type="submit"] {
    margin-top: 8px;
  }
</style>
