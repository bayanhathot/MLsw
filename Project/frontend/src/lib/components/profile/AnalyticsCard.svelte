<script>
	/** @type {{ label: string, value: string, detail?: string, icon?: string, accent?: string, tooltip?: string }} */
	let { label, value, detail = '', icon = '◌', accent = 'blue', tooltip = '' } = $props();
</script>

<article class="metric-card" class:violet={accent === 'violet'} class:cyan={accent === 'cyan'}>
	<div class="metric-top">
		<span class="metric-icon" aria-hidden="true">{icon}</span>
		<span class="metric-label">{label}</span>
		{#if tooltip}<button class="metric-help" type="button" title={tooltip} aria-label={tooltip}
				>?</button
			>{/if}
	</div>
	<strong>{value}</strong>
	{#if detail}<p>{detail}</p>{/if}
</article>

<style>
	.metric-card {
		position: relative;
		overflow: hidden;
		min-height: 164px;
		padding: 22px;
		border: 1px solid rgba(125, 183, 255, 0.18);
		border-radius: 22px;
		background:
			radial-gradient(circle at 86% 12%, rgba(59, 130, 246, 0.18), transparent 36%),
			linear-gradient(180deg, rgba(10, 21, 40, 0.95), rgba(5, 11, 22, 0.92));
		box-shadow: 0 16px 50px rgba(0, 0, 0, 0.28);
	}
	.metric-card::after {
		content: '';
		position: absolute;
		inset: auto -30% -65% 20%;
		height: 120px;
		background: radial-gradient(circle, rgba(82, 139, 255, 0.18), transparent 66%);
		pointer-events: none;
	}
	.metric-card.violet {
		background:
			radial-gradient(circle at 86% 12%, rgba(130, 93, 255, 0.2), transparent 36%),
			linear-gradient(180deg, rgba(16, 18, 42, 0.95), rgba(7, 10, 23, 0.92));
	}
	.metric-card.cyan {
		background:
			radial-gradient(circle at 86% 12%, rgba(61, 214, 204, 0.17), transparent 36%),
			linear-gradient(180deg, rgba(8, 24, 35, 0.95), rgba(4, 12, 20, 0.92));
	}
	.metric-top {
		display: flex;
		align-items: center;
		gap: 9px;
	}
	.metric-icon {
		display: grid;
		width: 30px;
		height: 30px;
		place-items: center;
		border: 1px solid rgba(125, 183, 255, 0.2);
		border-radius: 10px;
		background: rgba(125, 183, 255, 0.08);
		color: var(--accent-2);
		font-size: 14px;
	}
	.metric-label {
		color: #92a6c1;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.14em;
		text-transform: uppercase;
	}
	.metric-help {
		display: grid;
		width: 20px;
		height: 20px;
		margin-left: auto;
		place-items: center;
		border: 1px solid rgba(125, 183, 255, 0.24);
		border-radius: 999px;
		color: #8fa6c6;
		background: transparent;
		font-size: 11px;
		font-weight: 900;
		cursor: help;
	}
	strong {
		display: block;
		overflow: hidden;
		margin-top: 20px;
		color: #f8fbff;
		font-size: clamp(25px, 3vw, 36px);
		letter-spacing: -0.04em;
		line-height: 1.04;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	p {
		margin: 8px 0 0;
		color: #8fa0b8;
		font-size: 13px;
	}
</style>
