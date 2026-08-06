/**
 * File: src/lib/stores/feedStore.js
 *
 * Purpose:
 * Central frontend state for the feed: the post list, and the
 * like/share/delete mutations that update it in place.
 */

import { writable } from "svelte/store";
import {
  createPost,
  deletePost,
  getFeed,
  likePost,
  sharePost,
  unlikePost
} from "../services/postsApi.js";

/**
 * @typedef {"idle" | "loading" | "ready" | "error"} FeedStatus
 */

/**
 * @typedef {Object} FeedState
 * @property {FeedStatus} status
 * @property {import("../services/postsApi.js").Post[]} posts
 * @property {string | null} error
 */

/** @type {FeedState} */
const initialState = {
  status: "idle",
  posts: [],
  error: null
};

function createFeedStore() {
  const { subscribe, set, update } = writable(initialState);

  /**
   * @param {number} postId
   * @param {import("../services/postsApi.js").Post} updatedPost
   */
  function replacePost(postId, updatedPost) {
    update((state) => ({
      ...state,
      posts: state.posts.map((post) => (post.id === postId ? updatedPost : post))
    }));
  }

  return {
    subscribe,

    async load() {
      update((state) => ({ ...state, status: "loading", error: null }));

      try {
        const posts = await getFeed();
        set({ status: "ready", posts, error: null });
      } catch (err) {
        update((state) => ({
          ...state,
          status: "error",
          error: err instanceof Error ? err.message : "Failed to load the feed."
        }));
      }
    },

    /**
     * @param {{ prompt: string, description: string }} params
     * @returns {Promise<import("../services/postsApi.js").Post>}
     */
    async createPost(params) {
      const post = await createPost(params);

      update((state) => ({ ...state, posts: [post, ...state.posts] }));

      return post;
    },

    /**
     * @param {number} postId
     */
    async like(postId) {
      const updated = await likePost(postId);
      replacePost(postId, updated);
    },

    /**
     * @param {number} postId
     */
    async unlike(postId) {
      const updated = await unlikePost(postId);
      replacePost(postId, updated);
    },

    /**
     * @param {number} postId
     */
    async share(postId) {
      const { share_count } = await sharePost(postId);

      update((state) => ({
        ...state,
        posts: state.posts.map((post) =>
          post.id === postId ? { ...post, share_count } : post
        )
      }));
    },

    /**
     * @param {number} postId
     */
    async remove(postId) {
      await deletePost(postId);

      update((state) => ({
        ...state,
        posts: state.posts.filter((post) => post.id !== postId)
      }));
    }
  };
}

export const feedStore = createFeedStore();
