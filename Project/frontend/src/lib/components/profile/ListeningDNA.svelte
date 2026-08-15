<script>
	/** @type {{ dna?: { status: string, label?: string | null, summary?: string | null, dimensions?: { name: string, value: number }[], version?: string | null } }} */
	let { dna = { status: 'not_generated', label: null, summary: null, dimensions: [] } } = $props();
	let ready = $derived(
		dna?.status === 'ready' && Array.isArray(dna?.dimensions) && dna.dimensions.length > 0
	);
</script>

<section class="dna-panel" aria-labelledby="dna-heading">
	<div class="dna-glow" aria-hidden="true"></div>
	<div class="dna-copy">
		<p class="eyebrow">Evolving signature</p>
		<h3 id="dna-heading">Your Listening DNA</h3>
		{#if ready}
			<strong class="identity-name">{dna.label || 'Your music signature'}</strong>
			<p class="summary">
				{dna.summary || 'Your Listening DNA has been generated from your Cuemix behavior.'}
			</p>
		{:else}
			<strong class="identity-name">Still taking shape</strong>
			<p class="summary">
				Your Listening DNA will take shape as Cuemix learns from the music you actually play, skip,
				revisit, and explore.
			</p>
		{/if}
		<div class="dna-status">
			<span class:ready></span>{ready
				? `Model ${dna.version || 'ready'}`
				: 'Building from your listening history'}
		</div>
	</div>
	<div class="dna-visual">
		{#if ready}
			{#each dna.dimensions as dimension (dimension.name)}
				<div class="dimension">
					<div>
						<span>{dimension.name.replaceAll('_', ' ')}</span><strong
							>{Math.round(dimension.value * 100)}</strong
						>
					</div>
					<div class="meter">
						<span style={`width:${Math.round(dimension.value * 100)}%`}></span>
					</div>
				</div>
			{/each}
		{:else}
			<div class="orb" aria-hidden="true">
				<span></span><span></span><span></span>
				<div>DNA</div>
			</div>
		{/if}
	</div>
</section>

<style>
	.dna-panel {
		position: relative;
		overflow: hidden;
		display: grid;
		grid-template-columns: minmax(0, 1.25fr) minmax(180px, 0.75fr);
		gap: 34px;
		padding: 24px;
		border: 1px solid rgba(135, 116, 255, 0.28);
		border-radius: 28px;
		background: linear-gradient(
			135deg,
			rgba(12, 18, 42, 0.96),
			rgba(7, 13, 27, 0.94) 52%,
			rgba(11, 19, 35, 0.92)
		);
		box-shadow: 0 26px 80px rgba(0, 0, 0, 0.34);
	}
	.dna-glow {
		position: absolute;
		width: 430px;
		height: 430px;
		top: -260px;
		right: -110px;
		border-radius: 50%;
		background: radial-gradient(circle, rgba(119, 96, 255, 0.28), transparent 68%);
		pointer-events: none;
	}
	.dna-copy,
	.dna-visual {
		position: relative;
		z-index: 1;
	}
	.eyebrow {
		margin: 0 0 8px;
		color: #9d8cff;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.16em;
		text-transform: uppercase;
	}
	h3 {
		margin: 0;
		font-size: 26px;
		letter-spacing: -0.04em;
	}
	.identity-name {
		display: block;
		margin-top: 24px;
		color: #fff;
		font-size: clamp(24px, 3vw, 34px);
		letter-spacing: -0.05em;
	}
	.summary {
		max-width: 620px;
		margin: 12px 0 0;
		color: #9aa9bf;
		font-size: 14px;
		line-height: 1.7;
	}
	.dna-status {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 24px;
		color: #7789a3;
		font-size: 11px;
		font-weight: 800;
	}
	.dna-status > span {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: #6d7c94;
		box-shadow: 0 0 12px rgba(109, 124, 148, 0.5);
	}
	.dna-status > span.ready {
		background: #70e1c7;
		box-shadow: 0 0 14px rgba(112, 225, 199, 0.7);
	}
	.dna-visual {
		display: grid;
		align-content: center;
		gap: 15px;
	}
	.dimension {
		display: grid;
		gap: 7px;
	}
	.dimension > div:first-child {
		display: flex;
		justify-content: space-between;
		color: #9daac0;
		font-size: 12px;
		text-transform: capitalize;
	}
	.dimension strong {
		color: #dfe9ff;
	}
	.meter {
		height: 7px;
		border-radius: 999px;
		background: rgba(136, 116, 255, 0.1);
	}
	.meter span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: linear-gradient(90deg, #697fff, #9b77ff);
	}
	.orb {
		position: relative;
		display: grid;
		width: 130px;
		height: 130px;
		place-items: center;
		margin: auto;
		border: 1px solid rgba(139, 119, 255, 0.22);
		border-radius: 50%;
		background: radial-gradient(
			circle,
			rgba(100, 105, 255, 0.15),
			rgba(5, 11, 24, 0.3) 58%,
			transparent 59%
		);
		box-shadow:
			inset 0 0 50px rgba(97, 105, 255, 0.08),
			0 0 70px rgba(94, 96, 255, 0.08);
	}
	.orb > span {
		position: absolute;
		inset: 18px;
		border: 1px solid rgba(126, 143, 255, 0.17);
		border-radius: 50%;
		transform: rotate(28deg) scaleY(0.55);
	}
	.orb > span:nth-child(2) {
		transform: rotate(-28deg) scaleY(0.55);
	}
	.orb > span:nth-child(3) {
		transform: rotate(90deg) scaleY(0.55);
	}
	.orb div {
		display: grid;
		width: 58px;
		height: 58px;
		place-items: center;
		border: 1px solid rgba(160, 143, 255, 0.35);
		border-radius: 24px;
		background: rgba(91, 84, 207, 0.14);
		color: #b8adff;
		font-size: 13px;
		font-weight: 900;
		letter-spacing: 0.16em;
	}
	@media (max-width: 760px) {
		.dna-panel {
			grid-template-columns: 1fr;
			padding: 24px;
		}
		.orb {
			width: 150px;
			height: 150px;
		}
	}
</style>
