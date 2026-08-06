/**
 * File: src/lib/services/usersApi.js
 *
 * Purpose:
 * Frontend functions for looking up OTHER users: search and public profile.
 *
 * Backend endpoints:
 * - GET /users/search?q=
 * - GET /users/{username}
 * - GET /users/{username}/posts
 */

import { apiRequest } from "./api.js";

/**
 * @typedef {"self" | "none" | "pending_outgoing" | "pending_incoming" | "friends"} FriendStatus
 */

/**
 * @typedef {Object} UserPublic
 * @property {number} id
 * @property {string} username
 * @property {FriendStatus} friend_status
 */

/**
 * @typedef {Object} UserProfilePage
 * @property {number} id
 * @property {string} username
 * @property {string} created_at
 * @property {FriendStatus} friend_status
 * @property {string | null} display_name
 * @property {string | null} avatar_url
 * @property {string | null} bio
 * @property {string[] | null} favorite_genres
 */

/**
 * @param {string} query
 * @returns {Promise<UserPublic[]>}
 */
export function searchUsers(query) {
  return apiRequest(`/users/search?q=${encodeURIComponent(query)}`, {
    method: "GET"
  });
}

/**
 * @param {string} username
 * @returns {Promise<UserProfilePage>}
 */
export function getUserProfile(username) {
  return apiRequest(`/users/${encodeURIComponent(username)}`, {
    method: "GET"
  });
}

/**
 * @param {string} username
 * @returns {Promise<import("./postsApi.js").Post[]>}
 */
export function getUserPosts(username) {
  return apiRequest(`/users/${encodeURIComponent(username)}/posts`, {
    method: "GET"
  });
}
