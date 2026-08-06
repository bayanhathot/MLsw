/**
 * File: src/lib/services/postsApi.js
 *
 * Purpose:
 * Frontend functions for posts (feed entries): creating them, the feed
 * itself, likes, comments, and shares.
 *
 * Backend endpoints:
 * - POST   /posts
 * - GET    /posts/feed
 * - GET    /posts/{id}
 * - DELETE /posts/{id}
 * - POST   /posts/{id}/like
 * - DELETE /posts/{id}/like
 * - GET    /posts/{id}/comments
 * - POST   /posts/{id}/comments
 * - DELETE /posts/{id}/comments/{commentId}
 * - POST   /posts/{id}/share
 */

import { apiRequest } from "./api.js";

/**
 * @typedef {Object} MixSegment
 * @property {number} id
 * @property {number} position
 * @property {string} title
 * @property {string} artist
 * @property {string} audio_url
 * @property {string | null} cover_url
 * @property {number} start_second
 * @property {number} end_second
 * @property {string} transition_to_next
 * @property {string} source
 * @property {string} source_track_id
 */

/**
 * @typedef {Object} Mix
 * @property {number} id
 * @property {string} prompt
 * @property {string} created_at
 * @property {MixSegment[]} segments
 */

/**
 * @typedef {Object} Post
 * @property {number} id
 * @property {number} author_id
 * @property {string} author_username
 * @property {string} description
 * @property {Mix} mix
 * @property {number} like_count
 * @property {number} comment_count
 * @property {number} share_count
 * @property {boolean} liked_by_me
 * @property {string} created_at
 */

/**
 * @typedef {Object} Comment
 * @property {number} id
 * @property {number} author_id
 * @property {string} author_username
 * @property {string} body
 * @property {string} created_at
 */

/**
 * @param {{ prompt: string, description: string }} params
 * @returns {Promise<Post>}
 */
export function createPost(params) {
  return apiRequest("/posts", {
    method: "POST",
    body: JSON.stringify(params)
  });
}

/**
 * @param {{ limit?: number, offset?: number }} [params]
 * @returns {Promise<Post[]>}
 */
export function getFeed(params = {}) {
  const query = new URLSearchParams();
  if (params.limit) query.set("limit", String(params.limit));
  if (params.offset) query.set("offset", String(params.offset));

  const suffix = query.toString() ? `?${query.toString()}` : "";

  return apiRequest(`/posts/feed${suffix}`, { method: "GET" });
}

/**
 * @param {number} postId
 * @returns {Promise<Post>}
 */
export function getPost(postId) {
  return apiRequest(`/posts/${postId}`, { method: "GET" });
}

/**
 * @param {number} postId
 */
export function deletePost(postId) {
  return apiRequest(`/posts/${postId}`, { method: "DELETE" });
}

/**
 * @param {number} postId
 * @returns {Promise<Post>}
 */
export function likePost(postId) {
  return apiRequest(`/posts/${postId}/like`, { method: "POST" });
}

/**
 * @param {number} postId
 * @returns {Promise<Post>}
 */
export function unlikePost(postId) {
  return apiRequest(`/posts/${postId}/like`, { method: "DELETE" });
}

/**
 * @param {number} postId
 * @returns {Promise<Comment[]>}
 */
export function getComments(postId) {
  return apiRequest(`/posts/${postId}/comments`, { method: "GET" });
}

/**
 * @param {number} postId
 * @param {string} body
 * @returns {Promise<Comment>}
 */
export function addComment(postId, body) {
  return apiRequest(`/posts/${postId}/comments`, {
    method: "POST",
    body: JSON.stringify({ body })
  });
}

/**
 * @param {number} postId
 * @param {number} commentId
 */
export function deleteComment(postId, commentId) {
  return apiRequest(`/posts/${postId}/comments/${commentId}`, { method: "DELETE" });
}

/**
 * @param {number} postId
 * @returns {Promise<{ share_count: number }>}
 */
export function sharePost(postId) {
  return apiRequest(`/posts/${postId}/share`, { method: "POST" });
}
