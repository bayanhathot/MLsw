<script>
	/** @type {{ vibes?: { name: string, seconds: number, percentage: number }[] }} */
	let { vibes = [] } = $props();
	let visible = $derived(vibes.slice(0, 6));

	/** @param {number} seconds */
	function duration(seconds) {
		const safe = Math.max(0, Number(seconds || 0));
		const hours = Math.floor(safe / 3600);
		const minutes = Math.floor((safe % 3600) / 60);
		return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m` : `${Math.round(safe)}s`;
	}
</script>

<section class="vibe-panel" aria-labelledby="vibe-heading">
	<div class="section-heading">
		<div>
			<p>Listening context</p>
			<h3 id="vibe-heading">Your recurring vibes</h3>
		</div>
		{#if visible.length}<span>{visible.length} patterns</span>{/if}
	</div>

	{#if visible.length}
		<div class="vibe-grid">
			{#each visible as vibe, index (vibe.name)}
				<article class:lead={index === 0}>
					<div class="vibe-top">
						<div class="pulse" aria-hidden="true"><span></span></div>
						<div><strong>{vibe.name}</strong><small>{duration(vibe.seconds)} measured</small></div>
						<b>{vibe.percentage}%</b>
					</div>
					<div class="bar" aria-hidden="true">
						<span style={`width:${Math.max(4, Math.min(100, vibe.percentage))}%`}></span>
					</div>
				</article>
			{/each}
		</div>
	{:else}
		<div class="empty">
			<div class="empty-orbit" aria-hidden="true"><span></span></div>
			<strong>Your vibe pattern is still forming</strong>
			<p>
				As Cuemix records real listening sessions, repeated contexts such as focus, late night,
				energy and chill will appear here.
			</p>
		</div>
	{/if}
</section>

<style>
	.vibe-panel {
		padding: 24px;
		border: 1px solid rgba(125, 183, 255, 0.16);
		border-radius: 24px;
		background: linear-gradient(180deg, rgba(9, 18, 34, 0.9), rgba(5, 10, 20, 0.84));
		overflow: hidden;
	}
	.section-heading {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 16px;
		margin-bottom: 18px;
	}
	.section-heading p {
		margin: 0 0 5px;
		color: #7791b5;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.15em;
		text-transform: uppercase;
	}
	h3 {
		margin: 0;
		font-size: 22px;
		letter-spacing: -0.03em;
	}
	.section-heading > span {
		color: #71839c;
		font-size: 12px;
	}
	.vibe-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
	}
	.vibe-grid article {
		position: relative;
		padding: 15px;
		border: 1px solid rgba(255, 255, 255, 0.055);
		border-radius: 17px;
		background: rgba(255, 255, 255, 0.018);
	}
	.vibe-grid article.lead {
		border-color: rgba(117, 139, 255, 0.22);
		background: linear-gradient(135deg, rgba(77, 103, 231, 0.09), rgba(153, 95, 255, 0.045));
	}
	.vibe-top {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 10px;
	}
	.pulse {
		display: grid;
		width: 34px;
		height: 34px;
		place-items: center;
		border: 1px solid rgba(125, 183, 255, 0.14);
		border-radius: 12px;
		background: rgba(125, 183, 255, 0.045);
	}
	.pulse span {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: #8098ff;
		box-shadow: 0 0 18px rgba(111, 139, 255, 0.65);
	}
	.vibe-top > div:nth-child(2) {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.vibe-top strong {
		overflow: hidden;
		color: #e1edff;
		font-size: 13px;
		text-overflow: ellipsis;
		white-space: nowrap;
		text-transform: capitalize;
	}
	.vibe-top small {
		color: #6f829c;
		font-size: 10px;
	}
	.vibe-top b {
		color: #a8c6ed;
		font-size: 12px;
	}
	.bar {
		height: 4px;
		margin-top: 12px;
		border-radius: 99px;
		background: rgba(125, 183, 255, 0.07);
		overflow: hidden;
	}
	.bar span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: linear-gradient(90deg, #5688ff, #916eff);
		box-shadow: 0 0 12px rgba(92, 126, 255, 0.28);
	}
	.empty {
		display: grid;
		min-height: 210px;
		place-content: center;
		justify-items: center;
		text-align: center;
	}
	.empty-orbit {
		position: relative;
		display: grid;
		width: 58px;
		height: 58px;
		place-items: center;
		margin-bottom: 14px;
		border: 1px solid rgba(125, 183, 255, 0.15);
		border-radius: 50%;
	}
	.empty-orbit::before {
		content: '';
		position: absolute;
		inset: 9px;
		border: 1px dashed rgba(143, 111, 255, 0.3);
		border-radius: 50%;
	}
	.empty-orbit span {
		width: 9px;
		height: 9px;
		border-radius: 50%;
		background: #7f97ff;
		box-shadow: 0 0 16px rgba(118, 139, 255, 0.55);
	}
	.empty strong {
		color: #dfeaff;
	}
	.empty p {
		max-width: 520px;
		margin: 7px 0 0;
		color: #7d90aa;
		font-size: 13px;
		line-height: 1.6;
	}
	@media (max-width: 650px) {
		.vibe-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
