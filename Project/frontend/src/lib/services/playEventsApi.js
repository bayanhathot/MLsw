/**
 * File: src/lib/services/playEventsApi.js
 *
 * Purpose:
 * Report real listening time to the backend.
 *
 * Backend endpoint:
 * - POST /play-events
 */

import { apiRequest } from "./api.js";

/**
 * @param {{
 *   mixId: number,
 *   segmentId: number,
 *   secondsListened: number,
 *   eventType: "heartbeat" | "pause" | "ended" | "unmount",
 *   postId?: number
 * }} params
 */
export function reportPlayEvent(params) {
  return apiRequest("/play-events", {
    method: "POST",
    body: JSON.stringify({
      mix_id: params.mixId,
      segment_id: params.segmentId,
      seconds_listened: params.secondsListened,
      event_type: params.eventType,
      post_id: params.postId ?? null
    })
  });
}
