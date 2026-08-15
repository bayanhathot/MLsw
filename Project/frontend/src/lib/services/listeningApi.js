import { apiRequest } from './api.js';

/**
 * Persist one completed/abandoned playback moment. Track metadata is resolved
 * by the backend from the referenced Cuemix mix segment or DJ session.
 *
 * @param {{
 *  clientEventId: string,
 *  startedAt: string,
 *  endedAt?: string | null,
 *  secondsListened: number,
 *  skipped: boolean,
 *  mixId?: number | null,
 *  segmentId?: number | null,
 *  sessionId?: string | null,
 *  keepalive?: boolean
 * }} event
 */
export function recordListeningEvent(event) {
	return apiRequest('/listening-events', {
		method: 'POST',
		keepalive: Boolean(event.keepalive),
		body: JSON.stringify({
			client_event_id: event.clientEventId,
			started_at: event.startedAt,
			ended_at: event.endedAt ?? new Date().toISOString(),
			seconds_listened: Math.max(0, Math.round(event.secondsListened)),
			skipped: Boolean(event.skipped),
			mix_id: event.mixId ?? null,
			segment_id: event.segmentId ?? null,
			session_id: event.sessionId ?? null
		})
	});
}
