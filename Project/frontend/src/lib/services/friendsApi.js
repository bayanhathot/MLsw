/**
 * File: src/lib/services/friendsApi.js
 *
 * Purpose:
 * Frontend functions for sending, responding to, and listing friend requests.
 *
 * Backend endpoints:
 * - POST   /friends/requests
 * - GET    /friends/requests/incoming
 * - GET    /friends/requests/outgoing
 * - POST   /friends/requests/{id}/accept
 * - POST   /friends/requests/{id}/decline
 * - DELETE /friends/requests/{id}
 * - GET    /friends
 * - DELETE /friends/{username}
 */

import { apiRequest } from "./api.js";

/**
 * @typedef {Object} FriendRequest
 * @property {number} id
 * @property {import("./usersApi.js").UserPublic} other_user
 * @property {string} status
 * @property {string} created_at
 */

/**
 * @param {string} addresseeUsername
 * @returns {Promise<FriendRequest>}
 */
export function sendFriendRequest(addresseeUsername) {
  return apiRequest("/friends/requests", {
    method: "POST",
    body: JSON.stringify({ addressee_username: addresseeUsername })
  });
}

/**
 * @returns {Promise<FriendRequest[]>}
 */
export function getIncomingRequests() {
  return apiRequest("/friends/requests/incoming", { method: "GET" });
}

/**
 * @returns {Promise<FriendRequest[]>}
 */
export function getOutgoingRequests() {
  return apiRequest("/friends/requests/outgoing", { method: "GET" });
}

/**
 * @param {number} friendshipId
 * @returns {Promise<FriendRequest>}
 */
export function acceptRequest(friendshipId) {
  return apiRequest(`/friends/requests/${friendshipId}/accept`, { method: "POST" });
}

/**
 * @param {number} friendshipId
 * @returns {Promise<FriendRequest>}
 */
export function declineRequest(friendshipId) {
  return apiRequest(`/friends/requests/${friendshipId}/decline`, { method: "POST" });
}

/**
 * @param {number} friendshipId
 */
export function cancelRequest(friendshipId) {
  return apiRequest(`/friends/requests/${friendshipId}`, { method: "DELETE" });
}

/**
 * @returns {Promise<import("./usersApi.js").UserPublic[]>}
 */
export function getFriends() {
  return apiRequest("/friends", { method: "GET" });
}

/**
 * @param {string} username
 */
export function unfriend(username) {
  return apiRequest(`/friends/${encodeURIComponent(username)}`, { method: "DELETE" });
}
