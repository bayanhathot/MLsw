<!--
  File: src/routes/admin/debug/+page.svelte
  Purpose: Owner-only admin debug dashboard -- session-loop visibility
  (Prompt 16's pipeline_trace, per-stage latency), the Audius persistent-
  analysis cache (external_tracks), and a recent-activity/failure feed.

  Access control is entirely server-side (routers/admin_debug.py): every
  request here either succeeds with real data or 404s, exactly like
  navigating to a route that doesn't exist. This page adds no client-side
  role check of its own -- there is nothing to guard against by hiding
  markup, since an unauthorized visitor's every API call already 404s.

  Live updates reuse the app's single shared realtime WebSocket
  (realtimeSocket.js -- the same connection chat/notifications/feed use),
  subscribed to the "admin_debug" channel. See that module's own docstring
  for the subscribe/reconnect/resync contract this relies on.
-->

<script>
	import { onDestroy, onMount } from 'svelte';

	import {
		getAdminDebugEvents,
		getAdminDebugExternalTracks,
		getAdminDebugSessions
	} from '$lib/services/adminDebugApi.js';
	import { ApiError } from '$lib/services/api.js';
	import { connectionState, subscribe } from '$lib/services/realtimeSocket.js';
	import { formatUtcDate } from '$lib/utils/dates.js';

	/** @type {'loading' | 'not_found' | 'ready'} */
	let phase = $state('loading');

	/** @type {Array<Record<string, any>>} */
	let sessions = $state([]);
	/** @type {Array<Record<string, any>>} */
	let externalTracks = $state([]);
	/** @type {Array<Record<string, any>>} */
	let events = $state([]);
	let search = $state('');

	/** @type {string | null} */
	let selectedSessionId = $state(null);

	let unsubscribe = () => {};

	/** @param {string | null | undefined} value */
	function timeLabel(value) {
		if (!value) return '—';
		return formatUtcDate(
			value,
			(date) =>
				date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
			'—'
		);
	}

	async function loadSessions() {
		sessions = (await getAdminDebugSessions()).sessions;
	}

	async function loadExternalTracks() {
		externalTracks = (await getAdminDebugExternalTracks(search)).tracks;
	}

	async function loadEvents() {
		events = (await getAdminDebugEvents()).events;
	}

	async function loadAll() {
		await Promise.all([loadSessions(), loadExternalTracks(), loadEvents()]);
	}

	async function initialLoad() {
		try {
			await loadAll();
			phase = 'ready';
		} catch (error) {
			if (error instanceof ApiError && error.status === 404) {
				phase = 'not_found';
				return;
			}
			throw error;
		}
	}

	/** @param {string} type @param {any} data */
	function handleEvent(type, data) {
		// Invalidation-triggered refetch, same posture as the other debug
		// panel's own websocket (routers/debug.py's pipeline_debug_hub): a
		// client always re-fetches through the authorized REST endpoint
		// rather than trusting anything pushed over the socket directly.
		if (type === 'session_updated') void loadSessions();
		else if (type === 'external_track_updated') void loadExternalTracks();
		else if (type === 'activity_event') {
			events = [data, ...events].slice(0, 200);
		}
	}

	onMount(() => {
		void initialLoad().then(() => {
			if (phase !== 'ready') return;
			unsubscribe = subscribe('admin_debug', handleEvent, {
				// A *re*connect may have missed events entirely -- re-fetch
				// everything rather than trusting the feed stayed complete.
				onResync: () => void loadAll()
			});
		});
	});

	onDestroy(() => unsubscribe());

	/** @param {SubmitEvent} event */
	function submitSearch(event) {
		event.preventDefault();
		void loadExternalTracks();
	}
</script>

{#if phase === 'loading'}
	<p class="loading">Loading…</p>
{:else if phase === 'not_found'}
	<p class="not-found">Not found.</p>
{:else}
	<div class="admin-debug">
		<header class="admin-debug-header">
			<h1>Admin debug</h1>
			{#if $connectionState !== 'open'}
				<span class="conn-badge" class:reconnecting={$connectionState === 'reconnecting'}>
					{$connectionState === 'reconnecting' ? 'Reconnecting…' : 'Connecting…'}
				</span>
			{:else}
				<span class="conn-badge ok">Live</span>
			{/if}
		</header>

		<section class="card">
			<h2>Sessions ({sessions.length})</h2>
			<div class="session-list">
				{#each sessions as session (session.session_id)}
					{@const trace = session.trace}
					<button
						type="button"
						class="session-row"
						class:selected={selectedSessionId === session.session_id}
						onclick={() =>
							(selectedSessionId =
								selectedSessionId === session.session_id ? null : session.session_id)}
					>
						<span class="session-summary">
							<strong>{session.prompt}</strong>
							<span class="muted">{session.status} · {timeLabel(session.updated_at)}</span>
						</span>
						<span class="muted">{session.retriever_name}</span>
					</button>
					{#if selectedSessionId === session.session_id && trace}
						<div class="session-detail">
							<dl>
								<dt>Vibe</dt>
								<dd>{JSON.stringify(trace.vibe_understander ?? {})}</dd>

								<dt>Retrieval</dt>
								<dd>
									{trace.candidate_retriever?.implementation} · tier={trace.candidate_retriever
										?.tier} · fell_back={String(trace.candidate_retriever?.fell_back)} · candidates={trace
										.candidate_retriever?.candidate_count}
								</dd>

								<dt>Segment</dt>
								<dd>
									method={trace.segment_selector?.method} · {trace.segment_selector
										?.start_second}s–{trace.segment_selector?.end_second}s · bpm={trace
										.segment_selector?.bpm} · key={trace.segment_selector?.musical_key}
								</dd>

								<dt>Transition</dt>
								<dd>
									crossfade_ms={trace.transition_planner?.crossfade_ms} · style={trace
										.transition_planner?.style} · key_category={trace.transition_planner
										?.key_category ?? 'n/a'} · phrase_aligned={String(
										trace.transition_planner?.phrase_aligned
									)} · capped_by_reserved_window={String(
										trace.transition_planner?.capped_by_reserved_window
									)}
								</dd>

								<dt>Render</dt>
								<dd>
									{trace.audio_renderer?.implementation} · pass_through={String(
										trace.audio_renderer?.is_pass_through
									)}
									{#if trace.audio_renderer?.fallback_reason}
										· reason={trace.audio_renderer.fallback_reason}
									{/if}
								</dd>

								<dt>Timing</dt>
								<dd>
									{#each Object.entries(trace._timing ?? {}) as [key, value] (key)}
										<span class="timing-pill">{key}: {value}ms</span>
									{/each}
								</dd>

								{#if trace.audio_renderer?.skipped_tracks?.length}
									<dt>Skipped</dt>
									<dd>
										{#each trace.audio_renderer.skipped_tracks as skipped, i (i)}
											<div class="muted">
												{skipped.title} — {skipped.fallback_reason}
											</div>
										{/each}
									</dd>
								{/if}
							</dl>
						</div>
					{/if}
				{:else}
					<p class="muted">No sessions yet.</p>
				{/each}
			</div>
		</section>

		<section class="card">
			<h2>Audius analysis cache ({externalTracks.length})</h2>
			<form onsubmit={submitSearch} class="search-form">
				<input type="text" placeholder="Search artist or title…" bind:value={search} />
				<button type="submit">Search</button>
			</form>
			<table>
				<thead>
					<tr>
						<th>Title</th>
						<th>Artist</th>
						<th>Status</th>
						<th>Attempts</th>
						<th>Stale</th>
						<th>BPM</th>
						<th>Key</th>
						<th>Analyzed</th>
					</tr>
				</thead>
				<tbody>
					{#each externalTracks as track (track.id)}
						<tr>
							<td>{track.title}</td>
							<td>{track.artist}</td>
							<td>
								<span class="status-pill" class:bad={track.analysis_status === 'failed'}>
									{track.analysis_status}
								</span>
							</td>
							<td>{track.analysis_attempt_count}</td>
							<td>{track.is_stale ? 'yes' : ''}</td>
							<td>{track.bpm ?? '—'}</td>
							<td>{track.musical_key ?? '—'}</td>
							<td>{timeLabel(track.analyzed_at)}</td>
						</tr>
					{:else}
						<tr><td colspan="8" class="muted">No external tracks cached yet.</td></tr>
					{/each}
				</tbody>
			</table>
		</section>

		<section class="card">
			<h2>Recent activity ({events.length})</h2>
			<ul class="event-list">
				{#each events as event, i (i)}
					<li>
						<span class="event-kind">{event.event}</span>
						{#if event.session_id}<span class="muted">session={event.session_id}</span>{/if}
						{#if event.total_ms !== undefined}<span class="muted">{event.total_ms}ms</span>{/if}
						{#if event.reason}<span class="muted">{event.reason}</span>{/if}
					</li>
				{:else}
					<li class="muted">No recent activity.</li>
				{/each}
			</ul>
		</section>
	</div>
{/if}

<style>
	.loading,
	.not-found {
		padding: 32px;
		text-align: center;
		color: var(--text-muted, #888);
	}

	.admin-debug {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 16px 0 48px;
	}

	.admin-debug-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.conn-badge {
		font-size: 0.8rem;
		padding: 2px 10px;
		border-radius: 999px;
		background: #4443;
	}

	.conn-badge.ok {
		background: #2ecc7133;
		color: #1f9d5c;
	}

	.conn-badge.reconnecting {
		background: #f39c1233;
		color: #b8730a;
	}

	.card {
		border: 1px solid var(--border-color, #3333);
		border-radius: 12px;
		padding: 16px;
	}

	.session-list {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.session-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		width: 100%;
		text-align: left;
		padding: 8px;
		border: none;
		background: transparent;
		cursor: pointer;
		border-radius: 8px;
	}

	.session-row:hover,
	.session-row.selected {
		background: #8883;
	}

	.session-summary {
		display: flex;
		flex-direction: column;
	}

	.session-detail {
		padding: 8px 8px 16px;
	}

	.session-detail dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 4px 12px;
		font-size: 0.85rem;
	}

	.session-detail dt {
		font-weight: 600;
		color: var(--text-muted, #888);
	}

	.timing-pill {
		display: inline-block;
		background: #8882;
		border-radius: 6px;
		padding: 1px 6px;
		margin: 0 4px 4px 0;
		font-family: monospace;
	}

	.search-form {
		display: flex;
		gap: 8px;
		margin-bottom: 12px;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
	}

	th,
	td {
		text-align: left;
		padding: 6px 8px;
		border-bottom: 1px solid #8882;
	}

	.status-pill {
		padding: 1px 8px;
		border-radius: 999px;
		background: #2ecc7133;
	}

	.status-pill.bad {
		background: #e74c3c33;
	}

	.event-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
		max-height: 320px;
		overflow-y: auto;
	}

	.event-list li {
		display: flex;
		gap: 10px;
		font-size: 0.85rem;
		padding: 4px 0;
		border-bottom: 1px solid #8881;
	}

	.event-kind {
		font-weight: 600;
	}

	.muted {
		color: var(--text-muted, #888);
		font-size: 0.85rem;
	}
</style>
