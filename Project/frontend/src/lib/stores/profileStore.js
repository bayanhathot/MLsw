/**
 * File: src/lib/stores/profileStore.js
 *
 * Purpose:
 * Central frontend state for the current user's own profile.
 */

import { writable } from "svelte/store";
import { getMyProfile, updateMyProfile } from "../services/profileApi.js";

/**
 * @typedef {"idle" | "loading" | "ready" | "error"} ProfileStatus
 */

/**
 * @typedef {Object} ProfileState
 * @property {ProfileStatus} status
 * @property {import("../services/profileApi.js").Profile | null} profile
 * @property {string | null} error
 */

/** @type {ProfileState} */
const initialState = {
  status: "idle",
  profile: null,
  error: null
};

function createProfileStore() {
  const { subscribe, set, update } = writable(initialState);

  return {
    subscribe,

    async load() {
      update((state) => ({ ...state, status: "loading", error: null }));

      try {
        const profile = await getMyProfile();
        set({ status: "ready", profile, error: null });
      } catch (err) {
        update((state) => ({
          ...state,
          status: "error",
          error: err instanceof Error ? err.message : "Failed to load profile."
        }));
      }
    },

    /**
     * @param {Parameters<typeof updateMyProfile>[0]} changes
     */
    async update(changes) {
      const profile = await updateMyProfile(changes);
      update((state) => ({ ...state, profile, status: "ready", error: null }));

      return profile;
    }
  };
}

export const profileStore = createProfileStore();
