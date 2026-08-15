<script>
	/** @type {{ genres?: { name: string, seconds: number, percentage: number }[] }} */
	let { genres = [] } = $props();
	const palette = ['#4f8cff', '#8c78ff', '#40d4c4', '#dd73ff', '#79b8ff'];
	let topGenres = $derived(genres.slice(0, 5));
	let donut = $derived(buildDonut(topGenres));

	/** @param {{ name: string, seconds: number, percentage: number }[]} values */
	function buildDonut(values) {
		if (!values.length) return 'conic-gradient(rgba(125,183,255,.1) 0 100%)';
		let cursor = 0;
		const slices = values.map((item, index) => {
			const start = cursor;
			cursor += Number(item.percentage || 0);
			return `${palette[index % palette.length]} ${start}% ${cursor}%`;
		});
		if (cursor < 100) slices.push(`rgba(125,183,255,.08) ${cursor}% 100%`);
		return `conic-gradient(${slices.join(',')})`;
	}
</script>

<section class="panel" aria-labelledby="genre-heading">
	<div class="section-heading">
		<p>Sound map</p>
		<h3 id="genre-heading">Genre distribution</h3>
	</div>
	{#if topGenres.length}
		<div class="genre-layout">
			<div class="donut" style={`background:${donut}`} aria-label="Genre distribution chart">
				<div><strong>{topGenres[0].percentage}%</strong><span>{topGenres[0].name}</span></div>
			</div>
			<ul>
				{#each topGenres as genre, i (genre.name)}
					<li>
						<span class="dot" style={`background:${palette[i % palette.length]}`}></span><strong
							>{genre.name}</strong
						><span>{genre.percentage}%</span>
					</li>
				{/each}
			</ul>
		</div>
	{:else}
		<div class="empty">
			<span>◔</span><strong>Your sound map is empty</strong>
			<p>Genres will appear here as Cuemix records real listening events.</p>
		</div>
	{/if}
</section>

<style>
	.panel {
		padding: 24px;
		border: 1px solid rgba(125, 183, 255, 0.16);
		border-radius: 24px;
		background: linear-gradient(180deg, rgba(9, 18, 34, 0.88), rgba(5, 10, 20, 0.82));
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
	.genre-layout {
		display: grid;
		grid-template-columns: 190px 1fr;
		gap: 28px;
		align-items: center;
		margin-top: 24px;
	}
	.donut {
		position: relative;
		width: 174px;
		height: 174px;
		border-radius: 50%;
		box-shadow: 0 0 50px rgba(88, 108, 255, 0.12);
	}
	.donut::after {
		content: '';
		position: absolute;
		inset: 22px;
		border: 1px solid rgba(125, 183, 255, 0.12);
		border-radius: 50%;
		background: #07101f;
	}
	.donut div {
		position: absolute;
		inset: 0;
		z-index: 1;
		display: grid;
		place-content: center;
		text-align: center;
	}
	.donut strong {
		font-size: 30px;
		letter-spacing: -0.05em;
	}
	.donut span {
		max-width: 100px;
		overflow: hidden;
		color: #8498b5;
		font-size: 11px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	ul {
		display: grid;
		gap: 13px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	li {
		display: grid;
		grid-template-columns: 10px 1fr auto;
		gap: 10px;
		align-items: center;
		padding-bottom: 11px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.05);
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		box-shadow: 0 0 12px currentColor;
	}
	li strong {
		color: #dce8f8;
		font-size: 13px;
	}
	li > span:last-child {
		color: #7e90a9;
		font-size: 12px;
	}
	.empty {
		display: grid;
		min-height: 220px;
		place-items: center;
		align-content: center;
		text-align: center;
		color: #7f91aa;
	}
	.empty > span {
		color: var(--accent-2);
		font-size: 38px;
	}
	.empty strong {
		margin-top: 7px;
		color: #dfeaff;
	}
	.empty p {
		margin: 5px 0 0;
		font-size: 13px;
	}
	@media (max-width: 600px) {
		.genre-layout {
			grid-template-columns: 1fr;
			justify-items: center;
		}
		ul {
			width: 100%;
		}
	}
</style>
