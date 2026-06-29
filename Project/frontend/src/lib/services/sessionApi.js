import { mockSession } from "../data/mockSession.js";

/**
 * Purpose:
 * Isolates communication with the future backend API.
 *
 * How this connects to the project:
 * Today this file returns mock data. Later, this is where we replace mocks with
 * real endpoints such as POST /sessions/start, POST /sessions/{id}/feedback,
 * and POST /sessions/{id}/stop.
 *
 * Engineering decision:
 * UI components should not call fetch directly. Components call store actions;
 * the store calls this service. This keeps backend changes from breaking visual
 * components.
 */

/**
 * Simulates backend/model delay.
 *
 * @param {number} ms - Number of milliseconds to wait.
 * @returns {Promise<void>}
 */
function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Starts a mock AI DJ session.
 *
 * Future real version:
 * POST /sessions/start
 * Body: { prompt }
 * Response: { session_id, now_playing, reasoning, first_audio_url, ... }
 *
 * @param {{ prompt: string }} params
 * @returns {Promise<import("../types.js").DJSession>}
 */
export async function startSessionMock({ prompt }) {
  await wait(500);

  return {
    ...mockSession,
    prompt
  };
}

/**
 * Sends user feedback in mock mode.
 *
 * Future real version:
 * POST /sessions/{session_id}/feedback
 *
 * @param {{ sessionId: string | null, feedback: string }} params
 * @returns {Promise<{ ok: true }>}
 */
export async function sendFeedbackMock({ sessionId, feedback }) {
  console.info("Mock feedback sent", { sessionId, feedback });
  await wait(150);
  return { ok: true };
}

/**
 * Stops a mock AI DJ session.
 *
 * Future real version:
 * POST /sessions/{session_id}/stop
 *
 * @param {{ sessionId: string | null }} params
 * @returns {Promise<{ ok: true }>}
 */
export async function stopSessionMock({ sessionId }) {
  console.info("Mock session stopped", { sessionId });
  await wait(150);
  return { ok: true };
}
