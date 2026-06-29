/**
 * File: src/lib/services/sessionApi.js
 *
 * Purpose:
 * This file is the frontend API layer.
 * It hides the raw fetch() calls from the UI components.
 *
 * Components should not know backend URLs directly.
 * They should call functions like startSession(), sendFeedback(), and stopSession().
 */

const API_BASE_URL = "http://localhost:5000";

/**
 * Start a new AI DJ session by sending the user's prompt to FastAPI.
 *
 * @param {{ prompt: string }} params
 * @returns {Promise<import("$lib/types.js").Session>}
 */
export async function startSession(params) {
  const response = await fetch(`${API_BASE_URL}/sessions/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      prompt: params.prompt
    })
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || "Failed to start AI DJ session.");
  }

  return response.json();
}

/**
 * Send feedback to the active AI DJ session.
 *
 * @param {{ sessionId: string, feedback: string }} params
 * @returns {Promise<import("$lib/types.js").Session>}
 */
export async function sendFeedback(params) {
  const response = await fetch(`${API_BASE_URL}/sessions/${params.sessionId}/feedback`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      feedback: params.feedback
    })
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || "Failed to send feedback.");
  }

  return response.json();
}

/**
 * Stop the active AI DJ session.
 *
 * @param {{ sessionId: string }} params
 * @returns {Promise<{ session_id: string, status: string, message: string }>}
 */
export async function stopSession(params) {
  const response = await fetch(`${API_BASE_URL}/sessions/${params.sessionId}/stop`, {
    method: "POST"
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || "Failed to stop AI DJ session.");
  }

  return response.json();
}