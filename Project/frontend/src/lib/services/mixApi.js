/**
 * Frontend API functions for generating and sharing Zonix mixes.
 *
 * Authentication is handled by the HTTP-only cookie. The shared apiRequest
 * helper sends that cookie using credentials: "include".
 */

import { apiRequest } from "./api.js";

/**
 * Generate a mix and store it as a private draft.
 *
 * @param {string} prompt
 */
export function generateMix(prompt) {
  return apiRequest("/mixes/start", {
    method: "POST",
    body: JSON.stringify({ prompt })
  });
}

/**
 * Update a mix's title, description, and cover.
 *
 * @param {number} mixId
 * @param {{title: string, description?: string|null, cover_url?: string|null}} data
 */
export function updateMix(mixId, data) {
  return apiRequest(`/mixes/${mixId}`, {
    method: "PATCH",
    body: JSON.stringify(data)
  });
}

/**
 * Publish a draft mix in the community feed.
 *
 * @param {number} mixId
 */
export function publishMix(mixId) {
  return apiRequest(`/mixes/${mixId}/publish`, {
    method: "POST"
  });
}

/**
 * Get one page of published mixes.
 *
 * @param {{limit?: number, offset?: number, scope?: "discover"|"following"|"friends"}} options
 */
export function getFeed({ limit = 20, offset = 0, scope = "discover" } = {}) {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    scope
  });

  return apiRequest(`/mixes/feed?${query.toString()}`);
}

/** Follow a creator whose mixes should appear in the Following feed. */
export function followUser(userId) {
  return apiRequest(`/users/${userId}/follow`, {
    method: "PUT"
  });
}

/** Remove a creator from the current user's Following feed. */
export function unfollowUser(userId) {
  return apiRequest(`/users/${userId}/follow`, {
    method: "DELETE"
  });
}

/** Get mixes created by the logged-in user. */
export function getMyMixes() {
  return apiRequest("/mixes/mine");
}

/** Like a published mix. */
export function likeMix(mixId) {
  return apiRequest(`/mixes/${mixId}/like`, {
    method: "PUT"
  });
}

/** Remove the logged-in user's like. */
export function unlikeMix(mixId) {
  return apiRequest(`/mixes/${mixId}/like`, {
    method: "DELETE"
  });
}

/** Save a published mix as a private bookmark. */
export function saveMix(mixId) {
  return apiRequest(`/mixes/${mixId}/save`, {
    method: "PUT"
  });
}

/** Remove a mix from the logged-in user's saved library. */
export function unsaveMix(mixId) {
  return apiRequest(`/mixes/${mixId}/save`, {
    method: "DELETE"
  });
}

/** Get the logged-in user's saved mixes. */
export function getSavedMixes() {
  return apiRequest("/mixes/saved");
}
