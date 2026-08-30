<script>
	import { MIX_SCOPES } from '$lib/constants/mixScope.js';

	/**
	 * @type {{
	 *   value?: import('$lib/types.js').MixScope,
	 *   compact?: boolean,
	 *   onChange?: (value: import('$lib/types.js').MixScope) => void
	 * }}
	 */
	let { value = 'segments', compact = false, onChange = () => {} } = $props();
</script>

<fieldset class:compact class="scope-toggle">
	<legend>Mixing scope</legend>
	<div class="scope-options">
		{#each MIX_SCOPES as scope (scope.value)}
			<button
				type="button"
				class:selected={value === scope.value}
				aria-pressed={value === scope.value}
				title={scope.description}
				onclick={() => onChange(scope.value)}
			>
				<strong>{scope.label}</strong>
				{#if !compact}<small>{scope.description}</small>{/if}
			</button>
		{/each}
	</div>
</fieldset>

<style>
	.scope-toggle {
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

	.scope-options {
		display: flex;
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

	.compact .scope-options button {
		min-height: 38px;
		border-radius: 999px;
		padding: 8px 12px;
		text-align: center;
	}

	@media (max-width: 900px) {
		.scope-options {
			flex-wrap: wrap;
		}

		.scope-options button {
			flex: 1 1 45%;
		}
	}
</style>
