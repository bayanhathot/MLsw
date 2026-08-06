/**
 * File: src/lib/stores/friendsStore.js
 *
 * Purpose:
 * Central frontend state for friends and friend requests.
 */

import { writable } from "svelte/store";
import {
  acceptRequest,
  cancelRequest,
  declineRequest,
  getFriends,
  getIncomingRequests,
  getOutgoingRequests,
  sendFriendRequest,
  unfriend
} from "../services/friendsApi.js";

/**
 * @typedef {"idle" | "loading" | "ready" | "error"} FriendsStatus
 */

/**
 * @typedef {Object} FriendsState
 * @property {FriendsStatus} status
 * @property {import("../services/usersApi.js").UserPublic[]} friends
 * @property {import("../services/friendsApi.js").FriendRequest[]} incoming
 * @property {import("../services/friendsApi.js").FriendRequest[]} outgoing
 * @property {string | null} error
 */

/** @type {FriendsState} */
const initialState = {
  status: "idle",
  friends: [],
  incoming: [],
  outgoing: [],
  error: null
};

function createFriendsStore() {
  const { subscribe, set, update } = writable(initialState);

  async function refresh() {
    const [friends, incoming, outgoing] = await Promise.all([
      getFriends(),
      getIncomingRequests(),
      getOutgoingRequests()
    ]);

    set({ status: "ready", friends, incoming, outgoing, error: null });
  }

  return {
    subscribe,

    async load() {
      update((state) => ({ ...state, status: "loading", error: null }));

      try {
        await refresh();
      } catch (err) {
        update((state) => ({
          ...state,
          status: "error",
          error: err instanceof Error ? err.message : "Failed to load friends."
        }));
      }
    },

    /**
     * @param {string} username
     */
    async sendRequest(username) {
      await sendFriendRequest(username);
      await refresh();
    },

    /**
     * @param {number} friendshipId
     */
    async accept(friendshipId) {
      await acceptRequest(friendshipId);
      await refresh();
    },

    /**
     * @param {number} friendshipId
     */
    async decline(friendshipId) {
      await declineRequest(friendshipId);
      await refresh();
    },

    /**
     * @param {number} friendshipId
     */
    async cancel(friendshipId) {
      await cancelRequest(friendshipId);
      await refresh();
    },

    /**
     * @param {string} username
     */
    async remove(username) {
      await unfriend(username);
      await refresh();
    }
  };
}

export const friendsStore = createFriendsStore();
