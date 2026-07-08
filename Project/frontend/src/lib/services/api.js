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

const API_BASE_URL = "http://localhost:5000";

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
    throw new Error(data?.detail || data?.message || "Request failed.");
  }

  return data;
}