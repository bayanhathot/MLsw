import { mockSession } from "../data/mockSession.js";

/**
 * Backend communication boundary.
 *
 * Current MVP:
 * Returns mock Zonix data.
 *
 * Future backend:
 * Replace the mock with FastAPI/Flask calls such as:
 * - POST /sessions/start
 * - POST /sessions/{id}/feedback
 * - POST /sessions/{id}/stop
 */

/**
 * @param {number} ms
 * @returns {Promise<void>}
 */
function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * @param {{ prompt: string }} params
 * @returns {Promise<import("../types.js").Session>}
 */
export async function startSessionMock({ prompt }) {
  await wait(500);

  return {
    ...mockSession,
    prompt
  };
}

/**
 * @param {{ sessionId: string | null, feedback: string }} params
 * @returns {Promise<{ ok: true }>}
 */
export async function sendFeedbackMock({ sessionId, feedback }) {
  console.info("Mock Zonix feedback sent", { sessionId, feedback });
  await wait(150);
  return { ok: true };
}

/**
 * @param {{ sessionId: string | null }} params
 * @returns {Promise<{ ok: true }>}
 */
export async function stopSessionMock({ sessionId }) {
  console.info("Mock Zonix session stopped", { sessionId });
  await wait(150);
  return { ok: true };
}
