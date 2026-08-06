/**
 * File: src/lib/services/api.js
 *
 * Purpose:
 * Shared frontend API helper.
 *
 * Important for HTTP-only cookies:
 * Every request uses credentials: "include".
 *
 * This allows the browser to:
 * - accept the Set-Cookie header from /auth/login
 * - send the auth cookie automatically to /auth/me, /auth/logout, etc.
 *
 * The frontend never reads the JWT directly.
 */

const API_BASE_URL = "/api";

/**
 * Turn a FastAPI error body into a readable string.
 *
 * Our own HTTPException(detail="...") raises send `detail` as a plain
 * string, but FastAPI's automatic Pydantic validation errors (422s) send
 * `detail` as a LIST of {msg, loc, type} objects instead. Without this,
 * `new Error(data.detail)` on a list silently stringifies to
 * "[object Object]".
 *
 * @param {unknown} data
 * @returns {string}
 */
function extractErrorMessage(data) {
  const detail = /** @type {any} */ (data)?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.msg || String(item))
      .join(" ");
  }

  return /** @type {any} */ (data)?.message || "Request failed.";
}

/**
 * Send an HTTP request to the backend.
 *
 * @param {string} path
 * @param {RequestInit} options
 */
export async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });

  const contentType = response.headers.get("content-type") || "";

  const data = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => null);

  if (!response.ok) {
    throw new Error(extractErrorMessage(data));
  }

  return data;
}
