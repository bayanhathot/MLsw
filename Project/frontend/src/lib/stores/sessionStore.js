/**
 * File: src/lib/stores/sessionStore.js
 * Purpose: Central frontend state manager for the Zonix AI DJ session.
 * What it does:
 * - Stores the current prompt, session status, progress, generated mix, play/pause state, feedback, and errors.
 * - Exposes methods used by components: setPrompt, start, togglePlay, stop, sendFeedback, toggleReasoning, and reset.
 * - Runs a short start-up progress sequence before calling the FastAPI backend.
 * - Generates and persists a draft through the social mix API.
 * Why this file is important:
 * - Components stay simple because they read state from the store and call store methods.
 * - Backend integration stays isolated inside the services/store instead of being spread through UI components.
 */

import { writable } from "svelte/store";
import { APP_STATES } from "../constants/appStates.js";
import { generateMix } from "../services/mixApi.js";

/**
 * Zonix session store.
 *
 * Owns the prompt, player state, current mix, and feedback. Components stay
 * visual; this store owns product behavior.
 */

const startupSteps = [
  "Reading your prompt",
  "Scanning the private vault",
  "Sequencing momentum",
  "Preparing the first transition"
];

/** @type {import("../types.js").SessionState} */
const initialState = {
  status: APP_STATES.IDLE,
  prompt: "",
  currentStep: "",
  progress: 0,
  mix: null,
  isPlaying: false,
  reasoningOpen: false,
  selectedFeedback: null,
  error: null
};

function createSessionStore() {
  const { subscribe, set, update } = writable(initialState);

  /** @type {import("../types.js").SessionState} */
  let latestState = initialState;

  subscribe((value) => {
    latestState = value;
  });

  return {
    subscribe,

    /**
     * @param {string} prompt
     */
    setPrompt(prompt) {
      update((state) => ({
        ...state,
        prompt
      }));
    },

    async start() {
      const prompt = latestState.prompt.trim();

      if (!prompt || latestState.status === APP_STATES.STARTING) {
        return;
      }

      update((state) => ({
        ...state,
        status: APP_STATES.STARTING,
        currentStep: startupSteps[0],
        progress: 0,
        mix: null,
        isPlaying: false,
        reasoningOpen: false,
        selectedFeedback: null,
        error: null
      }));

      try {
        for (let i = 0; i < startupSteps.length; i += 1) {
          update((state) => ({
            ...state,
            currentStep: startupSteps[i],
            progress: Math.round(((i + 1) / startupSteps.length) * 100)
          }));

          await new Promise((resolve) => setTimeout(resolve, 550));
        }

        const mix = await generateMix(prompt);

        update((state) => ({
          ...state,
          status: APP_STATES.PLAYING,
          currentStep: "Zone active",
          progress: 100,
          mix,
          isPlaying: true
        }));
      } catch (error) {
        update((state) => ({
          ...state,
          status: APP_STATES.ERROR,
          isPlaying: false,
          error:
            error instanceof Error
              ? error.message
              : "Zonix could not create the mix. Try another prompt."
        }));
      }
    },

    togglePlay() {
      if (latestState.status !== APP_STATES.PLAYING) {
        return;
      }

      update((state) => ({
        ...state,
        isPlaying: !state.isPlaying
      }));
    },

    async stop() {
      if (
        latestState.status !== APP_STATES.PLAYING &&
        latestState.status !== APP_STATES.BUFFERING_NEXT
      ) {
        return;
      }

      update((state) => ({
        ...state,
        status: APP_STATES.STOPPED,
        isPlaying: false,
        currentStep: "Zone ended",
        progress: 0,
        selectedFeedback: null
      }));
    },

    /**
     * @param {string} feedback
     */
    sendFeedback(feedback) {
      if (latestState.status !== APP_STATES.PLAYING) {
        return;
      }

      if (!latestState.mix) {
        return;
      }

      // Mix feedback is UI-only until the backend exposes a mix feedback API.
      update((state) => ({
        ...state,
        selectedFeedback: feedback,
        error: null
      }));
    },

    playbackEnded() {
      update((state) => ({
        ...state,
        isPlaying: false,
        currentStep: "First segment finished"
      }));
    },

    toggleReasoning() {
      if (!latestState.mix) {
        return;
      }

      update((state) => ({
        ...state,
        reasoningOpen: !state.reasoningOpen
      }));
    },

    reset() {
      set({ ...initialState });
    }
  };
}

export const sessionStore = createSessionStore();
