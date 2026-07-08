/**
 * File: src/lib/services/sessionApi.js
 *
 * Purpose:
 * Frontend API layer for Zonix sessions.
 *
 * Current demo behavior:
 * - Sends prompt to backend.
 * - Backend returns a hardcoded demo.mp3 session.
 * - DJPlayerCard plays session.audioUrl.
 *
 * Important for HTTP-only cookies:
 * credentials: "include" is required.
 */

const API_BASE_URL = "http://localhost:5000";

/**
 * Helper for backend requests.
 *
 * @param {string} path
 * @param {RequestInit} options
 */
async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(data?.detail || data?.message || "Backend request failed.");
  }

  return data;
}

/**
 * Start a new AI DJ demo session.
 *
 * @param {{ prompt: string }} params
 * @returns {Promise<import("$lib/types.js").Session>}
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
 * @returns {Promise<import("$lib/types.js").Session>}
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
 * @returns {Promise<{ session_id: string, status: string, message: string }>}
 */
export async function stopSession(params) {
  return apiRequest(`/sessions/${params.sessionId}/stop`, {
    method: "POST"
  });
}