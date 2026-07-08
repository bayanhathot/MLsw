/**
 * File: src/lib/services/authApi.js
 *
 * Purpose:
 * Frontend functions for backend authentication endpoints.
 *
 * Backend endpoints:
 * - POST /auth/register
 * - POST /auth/login
 * - POST /auth/logout
 * - GET  /auth/me
 */

import { apiRequest } from "./api.js";

/**
 * @param {{ username: string, email: string, password: string }} params
 */
export function registerUser(params) {
  return apiRequest("/auth/register", {
    method: "POST",
    body: JSON.stringify({
      username: params.username,
      email: params.email,
      password: params.password
    })
  });
}

/**
 * @param {{ email: string, password: string }} params
 */
export function loginUser(params) {
  return apiRequest("/auth/login", {
    method: "POST",
    body: JSON.stringify({
      email: params.email,
      password: params.password
    })
  });
}

export function logoutUser() {
  return apiRequest("/auth/logout", {
    method: "POST"
  });
}

export function getCurrentUser() {
  return apiRequest("/auth/me", {
    method: "GET"
  });
}