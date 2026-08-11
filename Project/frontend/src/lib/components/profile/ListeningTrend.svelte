<script>
	/** @type {{ points?: { date: string, seconds: number }[] }} */
	let { points = [] } = $props();
	let chart = $derived(buildChart(points));

	/** @param {{ date: string, seconds: number }[]} values */
	function buildChart(values) {
		if (!values.length) return { coords: [], line: '', area: '', max: 0 };
		const width = 720,
			height = 190,
			padX = 18,
			padY = 16;
		const max = Math.max(60, ...values.map((item) => Number(item.seconds || 0)));
		const coords = values.map((item, index) => {
			const x =
				values.length === 1 ? width / 2 : padX + (index / (values.length - 1)) * (width - padX * 2);
			const y = height - padY - (Number(item.seconds || 0) / max) * (height - padY * 2);
			return { x, y, ...item };
		});
		const first = coords[0];
		const last = coords[coords.length - 1] || first;
		const line = coords.map((p) => `${p.x},${p.y}`).join(' ');
		const area = `M ${first.x} ${height - padY} L ${coords.map((p) => `${p.x} ${p.y}`).join(' L ')} L ${last.x} ${height - padY} Z`;
		return { coords, line, area, max };
	}

	/** @param {number} seconds */
	function shortDuration(seconds) {
		if (seconds >= 3600) return `${(seconds / 3600).toFixed(seconds >= 7200 ? 0 : 1)}h`;
		return `${Math.round(seconds / 60)}m`;
	}
</script>

<section class="trend-panel" aria-labelledby="trend-heading">
	<div class="section-heading">
		<div>
			<p>Rhythm over time</p>
			<h3 id="trend-heading">Listening trend</h3>
		</div>
		{#if chart.max}<span>Peak {shortDuration(chart.max)}</span>{/if}
	</div>
	{#if chart.coords.length}
		<div class="chart-wrap">
			<svg
				viewBox="0 0 720 190"
				role="img"
				aria-label="Listening time over the last 30 active calendar days"
			>
				<defs
					><linearGradient id="identityArea" x1="0" y1="0" x2="0" y2="1"
						><stop offset="0" stop-color="#6d8cff" stop-opacity=".32" /><stop
							offset="1"
							stop-color="#6d8cff"
							stop-opacity="0"
						/></linearGradient
					></defs
				>
				{#each [42, 86, 130, 174] as y (y)}<line x1="18" x2="702" {y} y2={y} class="grid" />{/each}
				<path d={chart.area} fill="url(#identityArea)" />
				<polyline points={chart.line} class="line" />
				{#each chart.coords as point, i (point.date)}<circle
						cx={point.x}
						cy={point.y}
						r={i === chart.coords.length - 1 ? 4 : 2.5}
						class:last={i === chart.coords.length - 1}
						><title>{point.date}: {shortDuration(point.seconds)}</title></circle
					>{/each}
			</svg>
			<div class="axis">
				<span>{chart.coords[0]?.date || ''}</span><span
					>{chart.coords[chart.coords.length - 1]?.date || ''}</span
				>
			</div>
		</div>
	{:else}
		<div class="empty">
			<strong>No timeline yet</strong>
			<p>Your listening trend starts after your first recorded session.</p>
		</div>
	{/if}
</section>

<style>
	.trend-panel {
		padding: 24px;
		border: 1px solid rgba(125, 183, 255, 0.16);
		border-radius: 24px;
		background: linear-gradient(180deg, rgba(9, 18, 34, 0.88), rgba(5, 10, 20, 0.82));
	}
	.section-heading {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 16px;
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
		color: #7f91aa;
		font-size: 12px;
	}
	.chart-wrap {
		margin-top: 18px;
	}
	svg {
		display: block;
		width: 100%;
		height: auto;
		overflow: visible;
	}
	.grid {
		stroke: rgba(125, 183, 255, 0.08);
		stroke-width: 1;
	}
	.line {
		fill: none;
		stroke: #7894ff;
		stroke-width: 3;
		stroke-linecap: round;
		stroke-linejoin: round;
		filter: drop-shadow(0 0 7px rgba(109, 140, 255, 0.45));
	}
	circle {
		fill: #6289ff;
		stroke: #dce8ff;
		stroke-width: 1.5;
	}
	circle.last {
		r: 5;
	}
	.axis {
		display: flex;
		justify-content: space-between;
		color: #61748e;
		font-size: 10px;
	}
	.empty {
		display: grid;
		min-height: 220px;
		place-content: center;
		text-align: center;
	}
	.empty strong {
		color: #dfeaff;
	}
	.empty p {
		margin: 6px 0 0;
		color: #7f91aa;
		font-size: 13px;
	}
</style>
