<script>
	import AnalyticsCard from './AnalyticsCard.svelte';
	import ArtistBreakdown from './ArtistBreakdown.svelte';
	import GenreDistribution from './GenreDistribution.svelte';
	import ListeningTrend from './ListeningTrend.svelte';
	import ListeningDNA from './ListeningDNA.svelte';
	import VibePatterns from './VibePatterns.svelte';
	import PrivacyToggle from './PrivacyToggle.svelte';
	import { parseUtcDate } from '$lib/utils/dates.js';

	/** @type {{ identity: Record<string, any>, isOwner?: boolean, privacyBusy?: boolean, periodBusy?: boolean, onPrivacyChange?: (value: 'private'|'friends'|'public') => void, onPeriodChange?: (value: '7d'|'30d'|'6m'|'all') => void }} */
	let {
		identity,
		isOwner = false,
		privacyBusy = false,
		periodBusy = false,
		onPrivacyChange = () => {},
		onPeriodChange = () => {}
	} = $props();
	let totalSeconds = $derived(Number(identity?.summary?.total_listening_seconds || 0));
	let hasData = $derived(totalSeconds > 0);

	/** @type {[('7d'|'30d'|'6m'|'all'), string][]} */
	const periodOptions = [
		['7d', '7D'],
		['30d', '30D'],
		['6m', '6M'],
		['all', 'All time']
	];

	/** @param {number} seconds */
	function duration(seconds) {
		const safe = Math.max(0, Number(seconds || 0));
		const hours = Math.floor(safe / 3600),
			minutes = Math.floor((safe % 3600) / 60);
		if (hours) return `${hours.toLocaleString()}h ${minutes}m`;
		if (minutes) return `${minutes}m`;
		return `${Math.floor(safe)}s`;
	}
	/** @param {{ seconds: number, percentage: number } | null | undefined} metric @param {string} fallback */
	function metricDetail(metric, fallback) {
		return metric ? `${duration(metric.seconds)} · ${metric.percentage}%` : fallback;
	}
	/** @param {string} value */
	function dateLabel(value) {
		const date = parseUtcDate(value);
		return Number.isNaN(date.getTime())
			? 'Recently'
			: date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
	}
</script>

<div class="identity-shell">
	<div class="identity-heading">
		<div>
			<p class="eyebrow">Understanding your sound</p>
			<h2>{isOwner ? 'Your Music Identity' : 'Music Identity'}</h2>
			<p class="intro">
				See the artists, genres, vibes, and listening patterns that are shaping your sound over
				time.
			</p>
		</div>
		{#if isOwner}<PrivacyToggle
				visibility={identity?.visibility || (identity?.is_public ? 'public' : 'private')}
				busy={privacyBusy}
				onToggle={onPrivacyChange}
			/>{/if}
	</div>

	<div class="period-row">
		<span>Time window</span>
		<div class="periods">
			{#each periodOptions as option (option[0])}<button
					class:active={(identity?.period || 'all') === option[0]}
					disabled={periodBusy}
					type="button"
					onclick={() => onPeriodChange(option[0])}>{option[1]}</button
				>{/each}
		</div>
	</div>

	<div class="metrics-grid">
		<AnalyticsCard
			label="Top artist"
			value={identity?.summary?.top_artist?.name || 'Not enough data'}
			detail={metricDetail(identity?.summary?.top_artist, 'Listen to reveal your leader.')}
			icon="♫"
		/>
		<AnalyticsCard
			label="Total listening"
			value={hasData ? duration(totalSeconds) : '0m'}
			detail={hasData
				? 'Actual playback time recorded by Zonix'
				: 'Your clock starts with your first play.'}
			icon="◷"
			accent="violet"
		/>
		<AnalyticsCard
			label="Top genre"
			value={identity?.summary?.top_genre?.name || 'Not enough data'}
			detail={identity?.summary?.top_genre
				? `${identity.summary.top_genre.percentage}% of tagged listening`
				: 'Appears as metadata arrives.'}
			icon="◈"
			accent="cyan"
		/>
		<AnalyticsCard
			label="Top vibe"
			value={identity?.summary?.top_vibe?.name || 'Still forming'}
			detail={identity?.summary?.top_vibe
				? `${identity.summary.top_vibe.percentage}% of classified listening`
				: 'Your recurring context will show here.'}
			icon="≈"
		/>
	</div>

	<div class="discovery-strip">
		<div>
			<strong>{identity?.summary?.artists_discovered || 0}</strong><span>artists heard</span>
		</div>
		<div><strong>{identity?.summary?.tracks_discovered || 0}</strong><span>tracks heard</span></div>
		<div>
			<strong>{identity?.summary?.listening_contexts || 0}</strong><span>listening sessions</span>
		</div>
		<div>
			<strong>{duration(identity?.summary?.average_context_seconds || 0)}</strong><span
				>avg. session</span
			>
		</div>
	</div>

	<div class="analytics-grid">
		<ArtistBreakdown artists={identity?.artists || []} /><GenreDistribution
			genres={identity?.genres || []}
		/>
	</div>

	<div class="secondary-grid">
		<section class="panel">
			<div class="section-heading">
				<div>
					<p>Most played</p>
					<h3>Top tracks</h3>
				</div>
			</div>
			{#if identity?.top_tracks?.length}<div class="rank-list">
					{#each identity.top_tracks.slice(0, 6) as track, index (`${track.artist}:${track.title}`)}<article
						>
							<b>{index + 1}</b>
							<div><strong>{track.title}</strong><span>{track.artist}</span></div>
							<time>{duration(track.seconds)}</time>
						</article>{/each}
				</div>{:else}<p class="empty-copy">Top tracks will appear after you listen.</p>{/if}
		</section>
		<section class="panel">
			<div class="section-heading">
				<div>
					<p>Your rhythm</p>
					<h3>When you listen</h3>
				</div>
			</div>
			{#if identity?.time_of_day?.length}<div class="day-list">
					{#each identity.time_of_day as item (item.name)}<div>
							<span>{item.name}</span>
							<div><i style={`width:${Math.max(3, item.percentage)}%`}></i></div>
							<strong>{item.percentage}%</strong>
						</div>{/each}
				</div>{:else}<p class="empty-copy">Time-of-day patterns will appear here.</p>{/if}
		</section>
	</div>

	<ListeningTrend points={identity?.listening_trend || []} />
	<div class="insight-grid">
		<VibePatterns vibes={identity?.vibes || []} /><ListeningDNA dna={identity?.listening_dna} />
	</div>

	<section class="panel">
		<div class="section-heading">
			<div>
				<p>Recent context</p>
				<h3>Listening sessions</h3>
			</div>
			<span>{identity?.recent_listening?.length || 0} recent</span>
		</div>
		{#if identity?.recent_listening?.length}<div class="recent-list">
				{#each identity.recent_listening as item (item.key)}<article>
						<div class="context-icon">{item.kind === 'mix' ? 'M' : 'DJ'}</div>
						<div class="recent-copy">
							<strong>{item.title}</strong><span
								>{item.subtitle || (item.kind === 'mix' ? 'Zonix mix' : 'AI DJ session')}</span
							>
						</div>
						<div class="recent-meta">
							<strong>{duration(item.seconds)}</strong><span>{dateLabel(item.started_at)}</span>
						</div>
					</article>{/each}
			</div>{:else}<div class="recent-empty">
				<strong>No listening sessions recorded yet</strong>
				<p>Play from your Library or start the DJ while signed in.</p>
			</div>{/if}
	</section>
</div>

<style>
	.identity-shell {
		display: grid;
		gap: 20px;
	}
	.identity-heading {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(360px, 520px);
		gap: 28px;
		align-items: end;
	}
	.eyebrow,
	.section-heading p {
		margin: 0 0 6px;
		color: #8199bd;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.16em;
		text-transform: uppercase;
	}
	h2 {
		margin: 0;
		font-size: clamp(32px, 5vw, 50px);
		letter-spacing: -0.055em;
	}
	.intro {
		max-width: 720px;
		margin: 10px 0 0;
		color: #8b9cb4;
		line-height: 1.65;
	}
	.period-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
		padding: 10px 12px;
		border: 1px solid rgba(125, 183, 255, 0.1);
		border-radius: 16px;
		background: rgba(7, 16, 31, 0.52);
	}
	.period-row > span {
		color: #7489a6;
		font-size: 11px;
		font-weight: 900;
		text-transform: uppercase;
	}
	.periods {
		display: flex;
		gap: 4px;
	}
	.periods button {
		border: 0;
		border-radius: 999px;
		padding: 7px 10px;
		background: transparent;
		color: #7489a6;
		font-size: 11px;
		font-weight: 900;
	}
	.periods button.active {
		background: rgba(76, 111, 229, 0.2);
		color: #dfeaff;
	}
	.metrics-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 14px;
	}
	.discovery-strip {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 8px;
	}
	.discovery-strip div {
		display: grid;
		gap: 3px;
		padding: 14px;
		border: 1px solid rgba(125, 183, 255, 0.1);
		border-radius: 15px;
		background: rgba(255, 255, 255, 0.015);
	}
	.discovery-strip strong {
		color: #cfe1fa;
		font-size: 20px;
	}
	.discovery-strip span {
		color: #6f839f;
		font-size: 11px;
	}
	.analytics-grid {
		display: grid;
		grid-template-columns: minmax(0, 1.18fr) minmax(330px, 0.82fr);
		gap: 18px;
	}
	.secondary-grid,
	.insight-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 18px;
	}
	.panel {
		padding: 24px;
		border: 1px solid rgba(125, 183, 255, 0.16);
		border-radius: 24px;
		background: linear-gradient(180deg, rgba(9, 18, 34, 0.88), rgba(5, 10, 20, 0.82));
	}
	.section-heading {
		display: flex;
		justify-content: space-between;
		gap: 16px;
		align-items: flex-end;
		margin-bottom: 18px;
	}
	.section-heading h3 {
		margin: 0;
		font-size: 22px;
		letter-spacing: -0.03em;
	}
	.section-heading > span {
		color: #71839d;
		font-size: 12px;
	}
	.rank-list {
		display: grid;
	}
	.rank-list article {
		display: grid;
		grid-template-columns: 24px 1fr auto;
		gap: 10px;
		align-items: center;
		padding: 9px 0;
		border-bottom: 1px solid rgba(255, 255, 255, 0.04);
	}
	.rank-list article > b {
		color: #6e82a1;
		font-size: 11px;
	}
	.rank-list article > div {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.rank-list strong {
		overflow: hidden;
		color: #dce8f8;
		font-size: 12px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.rank-list span,
	.rank-list time {
		color: #70839e;
		font-size: 10px;
	}
	.day-list {
		display: grid;
		gap: 11px;
	}
	.day-list > div {
		display: grid;
		grid-template-columns: 75px 1fr 42px;
		gap: 9px;
		align-items: center;
		color: #8fa4bf;
		font-size: 11px;
	}
	.day-list > div > div {
		height: 7px;
		overflow: hidden;
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.05);
	}
	.day-list i {
		display: block;
		height: 100%;
		border-radius: 999px;
		background: linear-gradient(90deg, #3978ec, #7561df);
	}
	.day-list strong {
		text-align: right;
		color: #9eb7d8;
	}
	.empty-copy {
		color: #7589a4;
		font-size: 12px;
	}
	.recent-list {
		display: grid;
		gap: 9px;
	}
	.recent-list article {
		display: grid;
		grid-template-columns: auto 1fr auto;
		gap: 13px;
		align-items: center;
		padding: 12px 13px;
		border: 1px solid rgba(255, 255, 255, 0.055);
		border-radius: 16px;
		background: rgba(255, 255, 255, 0.018);
	}
	.context-icon {
		display: grid;
		width: 40px;
		height: 40px;
		place-items: center;
		border: 1px solid rgba(125, 183, 255, 0.18);
		border-radius: 12px;
		background: linear-gradient(135deg, rgba(54, 105, 229, 0.2), rgba(123, 102, 255, 0.14));
		color: #9ec7ff;
		font-size: 11px;
		font-weight: 900;
	}
	.recent-copy,
	.recent-meta {
		display: grid;
		gap: 3px;
		min-width: 0;
	}
	.recent-copy strong {
		overflow: hidden;
		color: #e9f2ff;
		font-size: 13px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.recent-copy span,
	.recent-meta span {
		overflow: hidden;
		color: #74869f;
		font-size: 11px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.recent-meta {
		text-align: right;
	}
	.recent-meta strong {
		color: #b9cced;
		font-size: 12px;
	}
	.recent-empty {
		display: grid;
		min-height: 120px;
		place-content: center;
		text-align: center;
	}
	.recent-empty p {
		color: #7d90aa;
		font-size: 12px;
	}
	@media (max-width: 1050px) {
		.metrics-grid,
		.discovery-strip {
			grid-template-columns: repeat(2, 1fr);
		}
		.analytics-grid,
		.secondary-grid,
		.insight-grid,
		.identity-heading {
			grid-template-columns: 1fr;
		}
	}
	@media (max-width: 600px) {
		.metrics-grid,
		.discovery-strip {
			grid-template-columns: 1fr;
		}
		.period-row {
			align-items: flex-start;
			flex-direction: column;
		}
		.periods {
			width: 100%;
			overflow: auto;
		}
		.recent-list article {
			grid-template-columns: auto 1fr;
		}
		.recent-meta {
			grid-column: 2;
			text-align: left;
		}
	}
</style>
