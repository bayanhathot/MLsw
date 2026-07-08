import { apiRequest } from "./api.js";

/**
 * Start a new AI DJ session by sending the user's prompt to FastAPI.
 *
 * @param {{ prompt: string }} params
 */
export async function startSession(params) {
  return apiRequest("/sessions/start", {
    method: "POST",
    body: JSON.stringify({
      prompt: params.prompt
    })
  });
}

/**
 * Send feedback to the active AI DJ session.
 *
 * @param {{ sessionId: string, feedback: string }} params
 */
export async function sendFeedback(params) {
  return apiRequest(`/sessions/${params.sessionId}/feedback`, {
    method: "POST",
    body: JSON.stringify({
      feedback: params.feedback
    })
  });
}

/**
 * Stop the active AI DJ session.
 *
 * @param {{ sessionId: string }} params
 */
export async function stopSession(params) {
  return apiRequest(`/sessions/${params.sessionId}/stop`, {
    method: "POST"
  });
}