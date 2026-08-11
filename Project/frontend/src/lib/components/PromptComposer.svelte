<!--
  File: src/lib/components/PromptComposer.svelte
  Purpose: Prompt input used to start or retune an AI DJ session.
  What it does:
  - Lets the user describe the vibe they want.
  - Lets the user select quick preset prompts to fill the input.
  - Calls onPromptChange whenever the input changes.
  - Calls onStart when the user starts or updates the vibe.
  - Can render in normal mode before playback or compact overlay mode while playback is active.
  Product behavior:
  - Before starting, this is the main call-to-action.
  - While playing, it can be reopened from the Change vibe strip, then hidden again.
-->

<script>
	/**
	 * Prompt composer.
	 *
	 * In the guest MVP this is the main way to start Zonix. During playback it can
	 * also appear as a compact "change vibe" panel, opened from the small current
	 * vibe strip.
	 */

	import { PRESETS } from '$lib/constants/presets.js';

	/**
	 * @typedef {import("$lib/types.js").Preset} Preset
	 */

	/**
	 * @type {{
	 *   prompt?: string,
	 *   isStarting?: boolean,
	 *   isOverlay?: boolean,
	 *   showCancel?: boolean,
	 *   startLabel?: string,
	 *   onPromptChange?: (prompt: string) => void,
	 *   onStart?: () => void,
	 *   onCancel?: () => void
	 * }}
	 */
	let {
		prompt = '',
		isStarting = false,
		isOverlay = false,
		showCancel = false,
		startLabel = '▶ Start AI DJ',
		onPromptChange = () => {},
		onStart = () => {},
		onCancel = () => {}
	} = $props();

	/** @param {Event} event */
	function handlePromptInput(event) {
		const target = /** @type {HTMLInputElement} */ (event.currentTarget);
		onPromptChange(target.value);
	}

	/** @param {Preset} preset */
	function usePreset(preset) {
		onPromptChange(preset.prompt);
	}

	/** @param {SubmitEvent} event */
	function handleSubmit(event) {
		event.preventDefault();
		if (!isStarting && prompt.trim()) {
			onStart();
		}
	}
</script>

<form class:compact={isOverlay} class="composer card" onsubmit={handleSubmit}>
	<div class="composer-main">
		<div class="spark" aria-hidden="true">✦</div>

		<div class="title-row">
			<label class="prompt-label" for="vibe-prompt">
				{isOverlay ? 'Change the vibe...' : 'Describe the vibe you want...'}
			</label>

			{#if showCancel}
				<button class="ghost-button" type="button" onclick={onCancel}>Close</button>
			{/if}
		</div>

		<div class="input-row">
			<input
				id="vibe-prompt"
				value={prompt}
				oninput={handlePromptInput}
				placeholder="e.g. emotional Arabic vocals with smooth transitions"
				maxlength="1000"
				required
				autocomplete="off"
			/>

			<button class="primary-button" type="submit" disabled={isStarting || !prompt.trim()}>
				{isStarting ? 'Starting...' : startLabel}
			</button>
		</div>

		<div class="shortcut-row" aria-label="Quick vibe shortcuts">
			{#each PRESETS.slice(0, 5) as preset (preset.label)}
				<button class="preset-chip" type="button" onclick={() => usePreset(preset)}>
					{preset.label}
				</button>
			{/each}
		</div>
	</div>
</form>

<style>
	.composer {
		width: min(1080px, 100%);
		margin: -18px auto 30px;
		padding: 20px 24px;
		border-radius: 22px;
	}

	.composer.compact {
		margin: 0 auto 30px;
		border-color: rgba(125, 183, 255, 0.32);
		box-shadow:
			0 28px 90px rgba(0, 0, 0, 0.58),
			0 0 60px rgba(59, 130, 246, 0.12);
	}

	.composer-main {
		position: relative;
		z-index: 1;
		display: grid;
		grid-template-columns: 50px 1fr;
		gap: 14px 20px;
		align-items: center;
	}

	.spark {
		grid-row: span 2;
		width: 50px;
		height: 50px;
		display: grid;
		place-items: center;
		border-radius: 14px;
		color: var(--accent-2);
		background: rgba(125, 183, 255, 0.08);
		font-size: 22px;
	}

	.title-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
	}

	.prompt-label {
		color: var(--text-soft);
		font-size: 20px;
	}

	.ghost-button {
		border: 1px solid var(--border-muted);
		border-radius: 999px;
		padding: 8px 13px;
		color: var(--text-soft);
		background: rgba(255, 255, 255, 0.02);
		font-size: 13px;
		font-weight: 800;
	}

	.input-row {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 14px;
		align-items: center;
	}

	input {
		width: 100%;
		min-height: 58px;
		border: 1px solid var(--border-muted);
		border-radius: 16px;
		padding: 0 18px;
		color: var(--text-main);
		background: rgba(0, 0, 0, 0.22);
		outline: none;
	}

	input::placeholder {
		color: var(--text-muted);
	}

	input:focus {
		border-color: rgba(125, 183, 255, 0.42);
	}

	.shortcut-row {
		grid-column: 2;
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
	}

	.preset-chip {
		border: 1px solid var(--border-muted);
		border-radius: 999px;
		padding: 10px 16px;
		color: var(--text-soft);
		background: rgba(255, 255, 255, 0.025);
		font-size: 14px;
	}

	.preset-chip:hover,
	.ghost-button:hover {
		border-color: var(--accent-2);
		color: var(--text-main);
		background: rgba(125, 183, 255, 0.08);
	}

	@media (max-width: 780px) {
		.composer-main,
		.input-row {
			grid-template-columns: 1fr;
		}

		.spark,
		.shortcut-row {
			grid-column: auto;
		}

		.title-row {
			align-items: flex-start;
			flex-direction: column;
		}

		.primary-button {
			width: 100%;
		}
	}
</style>
