/** Canonical frontend API adapter for the `/sessions` workflow. */

import { apiRequest, backendMediaUrl } from './api.js';
import { normalizeSegment } from './segment.js';

/**
 * @param {unknown} value
 * @param {string} fallback
 */
function text(value, fallback = '') {
	return typeof value === 'string' && value.trim() ? value : fallback;
}

/**
 * Accept both the canonical camelCase session contract and segment-based
 * snake_case responses while the backend evolves.
 *
 * @param {unknown} value
 * @param {string} fallbackPrompt
 * @returns {import('../types.js').Session}
 */
export function normalizeSession(value, fallbackPrompt) {
	if (!value || typeof value !== 'object') {
		throw new TypeError('The server did not return a valid session.');
	}

	const raw = /** @type {Record<string, any>} */ (value);
	const rawSegments = Array.isArray(raw.segments) ? raw.segments : [];
	const segments = rawSegments.map(normalizeSegment);
	const firstSegment = segments[0];
	const rawNowPlaying = raw.nowPlaying ?? raw.now_playing ?? {};
	const vibeLabel = text(raw.vibeLabel ?? raw.vibe_label, text(raw.status, 'Your mix'));
	const nowPlaying = {
		title: text(rawNowPlaying.title, firstSegment?.title || 'Zonix session'),
		artist: text(rawNowPlaying.artist, firstSegment?.artist || 'Zonix AI DJ'),
		album: text(rawNowPlaying.album, 'Zonix mix'),
		coverUrl: text(rawNowPlaying.coverUrl ?? rawNowPlaying.cover_url, firstSegment?.coverUrl || ''),
		vibeLabel: text(rawNowPlaying.vibeLabel ?? rawNowPlaying.vibe_label, vibeLabel),
		role: text(rawNowPlaying.role, 'Current segment')
	};
	const rawReasoning = raw.reasoning ?? {};

	return {
		id: text(raw.id ?? raw.session_id, String(raw.mix_id ?? raw.id ?? '')),
		prompt: text(raw.prompt, fallbackPrompt),
		vibeLabel,
		nowPlaying,
		audioUrl: backendMediaUrl(text(raw.audioUrl ?? raw.audio_url, firstSegment?.audioUrl || '')),
		reasoning: {
			selectedMoment: text(
				rawReasoning.selectedMoment ?? rawReasoning.selected_moment,
				'Selected to match your requested vibe.'
			),
			transitionPlan: text(
				rawReasoning.transitionPlan ?? rawReasoning.transition_plan,
				segments.length > 1 ? 'Continue through the planned segments.' : 'Keep the flow consistent.'
			),
			nextDirection: text(
				rawReasoning.nextDirection ?? rawReasoning.next_direction,
				'Use your feedback to guide the next choice.'
			)
		},
		segments,
		selectedFeedback: text(raw.selectedFeedback ?? raw.selected_feedback) || null
	};
}

/**
 * @param {{ prompt: string, signal?: AbortSignal }} params
 */
export async function startSession({ prompt, signal }) {
	const response = await apiRequest('/sessions/start', {
		method: 'POST',
		body: JSON.stringify({ prompt }),
		// Runs the full pipeline (VibeUnderstander -> CandidateRetriever ->
		// SegmentSelector -> TransitionPlanner -> AudioRenderer); the Ollama
		// stage alone can take up to OLLAMA_TIMEOUT_SECONDS before falling
		// back, on top of retrieval/render, so this needs more room than the
		// 15s default other, lighter endpoints use.
		timeoutMs: 45_000,
		signal
	});

	return normalizeSession(response, prompt);
}

/**
 * @param {{ sessionId: string, feedback: string, signal?: AbortSignal }} params
 */
export async function sendFeedback({ sessionId, feedback, signal }) {
	const response = await apiRequest(`/sessions/${encodeURIComponent(sessionId)}/feedback`, {
		method: 'POST',
		body: JSON.stringify({ feedback }),
		// Re-runs the same full pipeline as startSession -- see its comment.
		timeoutMs: 45_000,
		signal
	});

	return normalizeSession(response, '');
}

/**
 * Continues a still-playing session onto its next track/segment with no
 * mutation to the session's intent -- called automatically when the current
 * one finishes, not by explicit user feedback (see sendFeedback above).
 *
 * @param {{ sessionId: string, signal?: AbortSignal }} params
 */
export async function advanceSession({ sessionId, signal }) {
	const response = await apiRequest(`/sessions/${encodeURIComponent(sessionId)}/advance`, {
		method: 'POST',
		// Re-runs the same full pipeline as startSession -- see its comment.
		timeoutMs: 45_000,
		signal
	});

	return normalizeSession(response, '');
}

/**
 * @param {{ sessionId: string, signal?: AbortSignal }} params
 */
export function stopSession({ sessionId, signal }) {
	return apiRequest(`/sessions/${encodeURIComponent(sessionId)}/stop`, {
		method: 'POST',
		signal
	});
}
