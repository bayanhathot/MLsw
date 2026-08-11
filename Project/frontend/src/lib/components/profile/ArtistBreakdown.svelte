<script>
	/** @type {{ artists?: { name: string, seconds: number, percentage: number }[] }} */
	let { artists = [] } = $props();
	let maxSeconds = $derived(Math.max(1, ...artists.map((artist) => Number(artist.seconds || 0))));

	/** @param {number} seconds */
	function duration(seconds) {
		const hours = Math.floor(seconds / 3600);
		const minutes = Math.floor((seconds % 3600) / 60);
		return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m` : `${seconds}s`;
	}
</script>

<section class="panel" aria-labelledby="artist-breakdown-heading">
	<div class="section-heading">
		<div>
			<p>Listening depth</p>
			<h3 id="artist-breakdown-heading">Your top artists</h3>
		</div>
		<span>{artists.length ? 'Based on actual play time' : 'Waiting for listening data'}</span>
	</div>
	{#if artists.length}
		<div class="artist-list">
			{#each artists.slice(0, 8) as artist, i (artist.name)}
				<div class="artist-row">
					<span class="rank">{String(i + 1).padStart(2, '0')}</span>
					<div class="artist-main">
						<div class="artist-meta">
							<strong>{artist.name}</strong><span
								>{duration(artist.seconds)} · {artist.percentage}%</span
							>
						</div>
						<div class="bar">
							<span style={`width:${Math.max(4, (artist.seconds / maxSeconds) * 100)}%`}></span>
						</div>
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<div class="empty">
			<span aria-hidden="true">♫</span>
			<strong>No artist history yet</strong>
			<p>Play a mix and Zonix will build this ranking from the seconds you actually listen.</p>
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
	.section-heading {
		display: flex;
		justify-content: space-between;
		gap: 18px;
		align-items: flex-end;
		margin-bottom: 20px;
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
		color: #74869e;
		font-size: 12px;
	}
	.artist-list {
		display: grid;
		gap: 14px;
	}
	.artist-row {
		display: grid;
		grid-template-columns: 34px 1fr;
		gap: 12px;
		align-items: center;
	}
	.rank {
		color: #536780;
		font-size: 12px;
		font-weight: 900;
	}
	.artist-main {
		display: grid;
		gap: 8px;
	}
	.artist-meta {
		display: flex;
		justify-content: space-between;
		gap: 14px;
	}
	.artist-meta strong {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: #e9f2ff;
		font-size: 14px;
	}
	.artist-meta span {
		flex: 0 0 auto;
		color: #7f91aa;
		font-size: 12px;
	}
	.bar {
		overflow: hidden;
		height: 7px;
		border-radius: 999px;
		background: rgba(125, 183, 255, 0.08);
	}
	.bar span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: linear-gradient(90deg, #427dff, #9a7dff);
		box-shadow: 0 0 18px rgba(90, 130, 255, 0.28);
	}
	.empty {
		display: grid;
		place-items: center;
		min-height: 210px;
		text-align: center;
		color: #7f91aa;
	}
	.empty > span {
		display: grid;
		width: 56px;
		height: 56px;
		place-items: center;
		border: 1px solid var(--border-soft);
		border-radius: 18px;
		background: rgba(125, 183, 255, 0.07);
		color: var(--accent-2);
		font-size: 25px;
	}
	.empty strong {
		margin-top: 12px;
		color: #dfeaff;
	}
	.empty p {
		max-width: 440px;
		margin: 6px auto 0;
		font-size: 13px;
		line-height: 1.6;
	}
	@media (max-width: 650px) {
		.section-heading,
		.artist-meta {
			align-items: flex-start;
			flex-direction: column;
		}
		.artist-meta {
			gap: 3px;
		}
	}
</style>
