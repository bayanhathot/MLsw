<!--
  File: src/lib/components/PipelineDebugPanel.svelte
  Purpose: Internal, observability-only view of live AI-DJ pipeline state
  and local Ollama health -- for the operator/developer running this
  deployment, not for ordinary visitors.

  Visibility: this component renders nothing at all unless GET
  /debug/pipeline succeeds. The backend gates that endpoint behind
  ENABLE_PIPELINE_DEBUG (off by default) *and* a logged-in user
  (routers/debug.py); a disabled or unauthorized response (404/401) is
  treated as "nothing to show" with no visible trace of the feature, not an
  error. This component never sends anything that could change pipeline
  behavior -- it only reads and displays.
-->

<script>
	import { onDestroy } from 'svelte';

	import { authStore } from '$lib/stores/authStore.js';
	import { getPipelineDebug, pipelineDebugWebSocketUrl } from '$lib/services/debugApi.js';
	import { formatUtcDate } from '$lib/utils/dates.js';

	/** @type {import('$lib/types.js').PipelineDebugState | null} */
	let data = $state(null);
	let visible = $state(false);
	let collapsed = $state(true);
	let attempted = false;

	/** @type {WebSocket | null} */
	let socket = null;
	/** @type {ReturnType<typeof setTimeout> | null} */
	let refreshTimer = null;

	async function load() {
		try {
			data = await getPipelineDebug();
			visible = true;
			if (!socket) connectSocket();
		} catch {
			// Disabled (404) or unauthorized (401) -- both mean "nothing to
			// show", not an error to surface.
			visible = false;
		}
	}

	function connectSocket() {
		const url = pipelineDebugWebSocketUrl();
		if (!url) return;
		try {
			socket = new WebSocket(url);
			socket.onopen = () => socket?.send('ready');
			socket.onmessage = () => {
				if (refreshTimer) clearTimeout(refreshTimer);
				refreshTimer = setTimeout(() => void load(), 300);
			};
		} catch {
			// Best-effort realtime only; the panel still works on its next manual refresh.
		}
	}

	function closeSocket() {
		if (socket) {
			socket.close();
			socket = null;
		}
	}

	$effect(() => {
		if ($authStore.status === 'authenticated' && !attempted) {
			attempted = true;
			void load();
		} else if ($authStore.status === 'guest') {
			attempted = false;
			visible = false;
			data = null;
			closeSocket();
		}
	});

	onDestroy(() => {
		if (refreshTimer) clearTimeout(refreshTimer);
		closeSocket();
	});

	/** @param {{ at: string | null, latency_ms: number | null, ok: boolean | null }} lastCall */
	function lastCallLabel(lastCall) {
		if (!lastCall?.at) return 'No calls yet';
		const when = formatUtcDate(lastCall.at, (date) =>
			date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
		);
		return `${when} · ${lastCall.latency_ms}ms · ${lastCall.ok ? 'ok' : 'fell back to deterministic parse'}`;
	}

	/** @param {string} value */
	function updatedLabel(value) {
		return formatUtcDate(
			value,
			(date) =>
				date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
			'—'
		);
	}
</script>

{#if visible && data}
	<div class="pipeline-debug">
		<button
			class="debug-toggle"
			type="button"
			onclick={() => (collapsed = !collapsed)}
			aria-expanded={!collapsed}
		>
			<span class="debug-dot" class:ok={data.ollama.reachable} class:bad={!data.ollama.reachable}
			></span>
			Pipeline debug
			<span class="debug-caret">{collapsed ? '▸' : '▾'}</span>
		</button>

		{#if !collapsed}
			<section class="debug-body card" aria-label="AI-DJ pipeline debug panel">
				<h4>Ollama</h4>
				<dl class="debug-facts">
					<div>
						<dt>Configured</dt>
						<dd>{data.ollama.configured ? 'yes' : 'no'}</dd>
					</div>
					<div>
						<dt>Reachable</dt>
						<dd class:ok={data.ollama.reachable} class:bad={!data.ollama.reachable}>
							{data.ollama.reachable ? 'yes' : 'no'}
						</dd>
					</div>
					<div>
						<dt>Configured model</dt>
						<dd>{data.ollama.configured_model || '—'}</dd>
					</div>
					<div>
						<dt>Loaded model(s)</dt>
						<dd>{data.ollama.loaded_models.length ? data.ollama.loaded_models.join(', ') : '—'}</dd>
					</div>
					<div>
						<dt>Last call</dt>
						<dd>{lastCallLabel(data.ollama.last_call)}</dd>
					</div>
					{#if data.ollama.error}
						<div>
							<dt>Error</dt>
							<dd class="bad">{data.ollama.error}</dd>
						</div>
					{/if}
				</dl>

				<h4>Recent sessions ({data.sessions.length})</h4>
				{#if data.sessions.length === 0}
					<p class="debug-empty">No sessions yet.</p>
				{:else}
					<ul class="debug-sessions">
						{#each data.sessions as session (session.session_id)}
							<li>
								<div class="debug-session-head">
									<span class="debug-session-id">{session.session_id}</span>
									<span class="debug-session-status">{session.status}</span>
									<span class="debug-session-time">{updatedLabel(session.updated_at)}</span>
								</div>
								<p class="debug-prompt">&ldquo;{session.prompt}&rdquo;</p>
								{#if session.trace}
									{@const trace = session.trace}
									<dl class="debug-facts">
										<div>
											<dt>VibeUnderstander</dt>
											<dd>
												{trace.vibe_understander?.implementation} · {trace.vibe_understander
													?.invoked
													? 'invoked'
													: 'not invoked (deterministic)'}
											</dd>
										</div>
										<div>
											<dt>CandidateRetriever</dt>
											<dd>
												{trace.candidate_retriever?.implementation} ({trace.candidate_retriever
													?.name}) · {trace.candidate_retriever?.candidate_count} candidate(s) · selected
												&ldquo;{trace.candidate_retriever?.selected_track?.title}&rdquo;
											</dd>
										</div>
										<div>
											<dt>SegmentSelector</dt>
											<dd>
												{trace.segment_selector?.implementation} · {trace.segment_selector?.method} ({trace
													.segment_selector?.start_second}s&ndash;{trace.segment_selector
													?.end_second}s)
											</dd>
										</div>
										<div>
											<dt>TransitionPlanner</dt>
											<dd>
												{trace.transition_planner?.implementation} · {trace.transition_planner
													?.style}, {trace.transition_planner?.crossfade_ms}ms
											</dd>
										</div>
										<div>
											<dt>AudioRenderer</dt>
											<dd>
												{trace.audio_renderer?.implementation} · {trace.audio_renderer
													?.is_pass_through
													? 'pass-through (no blend)'
													: 'rendered'}
											</dd>
										</div>
									</dl>
								{:else}
									<p class="debug-empty">No trace recorded yet.</p>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			</section>
		{/if}
	</div>
{/if}

<style>
	.pipeline-debug {
		position: fixed;
		right: 16px;
		bottom: 16px;
		z-index: 40;
		display: flex;
		flex-direction: column-reverse;
		align-items: flex-end;
		gap: 8px;
		font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
	}

	.debug-toggle {
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 7px 12px;
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-sm);
		background: var(--bg-card-solid);
		color: var(--text-soft);
		font-family: inherit;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		cursor: pointer;
	}

	.debug-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--danger);
	}

	.debug-dot.ok {
		background: var(--success);
	}

	.debug-caret {
		color: var(--accent-2);
	}

	.debug-body {
		width: min(380px, calc(100vw - 32px));
		max-height: min(70vh, 560px);
		overflow-y: auto;
		padding: 16px;
	}

	.debug-body h4 {
		margin: 0 0 8px;
		color: var(--accent-2);
		font-size: 11px;
		font-weight: 800;
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}

	.debug-body h4:not(:first-child) {
		margin-top: 16px;
	}

	.debug-facts {
		display: grid;
		gap: 6px;
		margin: 0;
	}

	.debug-facts > div {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		font-size: 11.5px;
		line-height: 1.4;
	}

	.debug-facts dt {
		flex: 0 0 auto;
		color: var(--text-muted);
	}

	.debug-facts dt::after {
		content: ':';
	}

	.debug-facts dd {
		flex: 1 1 auto;
		margin: 0;
		color: var(--text-soft);
		word-break: break-word;
	}

	.debug-facts dd.ok {
		color: var(--success);
	}

	.debug-facts dd.bad {
		color: var(--danger);
	}

	.debug-empty {
		margin: 0;
		color: var(--text-muted);
		font-size: 11.5px;
	}

	.debug-sessions {
		display: grid;
		gap: 10px;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.debug-sessions > li {
		padding: 10px;
		border: 1px solid var(--border-muted);
		border-radius: 12px;
		background: var(--bg-panel);
	}

	.debug-session-head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		margin-bottom: 4px;
		color: var(--text-muted);
		font-size: 10.5px;
	}

	.debug-session-id {
		overflow: hidden;
		color: var(--accent-3);
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.debug-session-status {
		padding: 1px 6px;
		border-radius: var(--radius-sm);
		background: var(--bg-card-solid);
		text-transform: uppercase;
	}

	.debug-session-time {
		margin-left: auto;
	}

	.debug-prompt {
		margin: 0 0 8px;
		color: var(--text-soft);
		font-size: 11.5px;
		font-style: italic;
	}
</style>
