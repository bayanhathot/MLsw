<script>
	import { AUTO_MIX_MODES } from '$lib/constants/autoMixModes.js';

	/**
	 * @type {{
	 *   value?: import('$lib/types.js').AutoMixMode | null,
	 *   compact?: boolean,
	 *   onChange?: (value: import('$lib/types.js').AutoMixMode | null) => void,
	 *   onDefaultPrompt?: (prompt: string) => void
	 * }}
	 */
	let { value = null, compact = false, onChange = () => {}, onDefaultPrompt = () => {} } = $props();

	/** @param {(typeof AUTO_MIX_MODES)[number]} mode */
	function choose(mode) {
		onChange(/** @type {import('$lib/types.js').AutoMixMode} */ (mode.value));
		onDefaultPrompt(mode.defaultPrompt);
	}
</script>

<fieldset class:compact class="mode-selector">
	<legend>Auto-mix mode <span>deterministic preset</span></legend>
	<div class="mode-options">
		{#each AUTO_MIX_MODES as mode (mode.value)}
			<button
				type="button"
				class:selected={value === mode.value}
				aria-pressed={value === mode.value}
				title={mode.description}
				onclick={() => choose(mode)}
			>
				<strong>{mode.label}</strong>
				{#if !compact}<small>{mode.description}</small>{/if}
			</button>
		{/each}
		<button
			type="button"
			class="custom"
			class:selected={value === null}
			aria-pressed={value === null}
			onclick={() => onChange(null)}
		>
			<strong>Custom</strong>
			{#if !compact}<small>Use only your free-text prompt</small>{/if}
		</button>
	</div>
</fieldset>

<style>
	.mode-selector {
		min-width: 0;
		margin: 0;
		border: 0;
		padding: 0;
	}

	legend {
		margin-bottom: 9px;
		padding: 0;
		color: var(--text-soft);
		font-size: 13px;
		font-weight: 900;
		letter-spacing: 0.04em;
	}

	legend span {
		margin-left: 6px;
		color: var(--text-muted);
		font-size: 11px;
		font-weight: 700;
	}

	.mode-options {
		display: grid;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		gap: 8px;
	}

	button {
		min-height: 54px;
		border: 1px solid var(--border-muted);
		border-radius: 13px;
		padding: 8px 10px;
		color: var(--text-soft);
		background: rgba(255, 255, 255, 0.025);
		text-align: left;
	}

	button strong,
	button small {
		display: block;
	}

	button strong {
		font-size: 13px;
	}

	button small {
		margin-top: 3px;
		color: var(--text-muted);
		font-size: 10px;
		line-height: 1.25;
	}

	button:hover,
	button.selected {
		border-color: var(--accent-2);
		color: white;
		background: rgba(59, 130, 246, 0.16);
	}

	button.selected {
		box-shadow: inset 0 0 0 1px rgba(125, 183, 255, 0.28);
	}

	.compact .mode-options {
		display: flex;
		flex-wrap: wrap;
	}

	.compact button {
		min-height: 38px;
		border-radius: 999px;
		padding: 8px 12px;
		text-align: center;
	}

	@media (max-width: 900px) {
		.mode-options {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		button.custom {
			grid-column: span 2;
		}
	}
</style>
