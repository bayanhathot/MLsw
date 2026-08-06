/**
 * File: src/lib/services/profileApi.js
 *
 * Purpose:
 * Frontend functions for profile customization and listening stats.
 *
 * Backend endpoints:
 * - GET   /users/me/profile
 * - PATCH /users/me/profile
 * - GET   /users/{username}/stats
 */

import { apiRequest } from "./api.js";

/**
 * @typedef {"dark" | "light" | "system"} ThemePreference
 */

/**
 * @typedef {Object} Profile
 * @property {string | null} display_name
 * @property {string | null} avatar_url
 * @property {string | null} bio
 * @property {string[] | null} favorite_genres
 * @property {ThemePreference} theme_preference
 */

/**
 * @typedef {Object} FavoriteArtist
 * @property {string} artist
 * @property {number} seconds_listened
 */

/**
 * @typedef {Object} ProfileStats
 * @property {number} minutes_listened
 * @property {FavoriteArtist[]} favorite_artists
 */

/**
 * @returns {Promise<Profile>}
 */
export function getMyProfile() {
  return apiRequest("/users/me/profile", { method: "GET" });
}

/**
 * @param {Partial<{
 *   display_name: string | null,
 *   avatar_url: string | null,
 *   bio: string | null,
 *   favorite_genres: string[] | null,
 *   theme_preference: ThemePreference
 * }>} updates
 * @returns {Promise<Profile>}
 */
export function updateMyProfile(updates) {
  return apiRequest("/users/me/profile", {
    method: "PATCH",
    body: JSON.stringify(updates)
  });
}

/**
 * @param {string} username
 * @returns {Promise<ProfileStats>}
 */
export function getUserStats(username) {
  return apiRequest(`/users/${encodeURIComponent(username)}/stats`, { method: "GET" });
}
