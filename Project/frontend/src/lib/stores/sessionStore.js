/**
 * File: src/lib/stores/sessionStore.js
 * Purpose: Central frontend state manager for the Zonix AI DJ session.
 * What it does:
 * - Stores the current prompt, session status, progress, current session data, play/pause state, feedback, and errors.
 * - Exposes methods used by components: setPrompt, start, togglePlay, stop, sendFeedback, toggleReasoning, and reset.
 * - Runs a short start-up progress sequence before calling the FastAPI backend.
 * - Sends prompt, feedback, and stop requests to the backend through sessionApi.js.
 * Why this file is important:
 * - Components stay simple because they read state from the store and call store methods.
 * - Backend integration stays isolated inside the services/store instead of being spread through UI components.
 */

import { writable } from "svelte/store";
import { APP_STATES } from "../constants/appStates.js";
import {
  sendFeedback as apiSendFeedback,
  startSession as apiStartSession,
  stopSession as apiStopSession
} from "../services/sessionApi.js";

/**
 * Zonix session store.
 *
 * Owns the prompt, player state, current session, and feedback. Components stay
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
  session: null,
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
        session: null,
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

        const session = await apiStartSession({ prompt });

        update((state) => ({
          ...state,
          status: APP_STATES.PLAYING,
          currentStep: "Zone active",
          progress: 100,
          session,
          isPlaying: true
        }));
      } catch {
        update((state) => ({
          ...state,
          status: APP_STATES.ERROR,
          isPlaying: false,
          error:
            "Zonix could not start the session. Try another prompt or choose a preset."
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

      const sessionId = latestState.session?.id ?? null;
      if (sessionId) {
        await apiStopSession({ sessionId });
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
    async sendFeedback(feedback) {
      if (latestState.status !== APP_STATES.PLAYING) {
        return;
      }

      const sessionId = latestState.session?.id ?? null;
      if (!sessionId) {
        return;
      }

      try {
        const updatedSession = await apiSendFeedback({ sessionId, feedback });

        update((state) => ({
          ...state,
          session: updatedSession,
          selectedFeedback: feedback,
          error: null
        }));
      } catch {
        update((state) => ({
          ...state,
          error: "Zonix could not send the feedback to the backend."
        }));
      }
    },

    toggleReasoning() {
      if (!latestState.session) {
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
