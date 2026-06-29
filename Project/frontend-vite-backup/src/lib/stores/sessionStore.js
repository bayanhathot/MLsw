import { writable } from "svelte/store";
import { APP_STATES } from "../constants/appStates.js";
import {
  sendFeedbackMock,
  startSessionMock,
  stopSessionMock
} from "../services/sessionApi.js";

/**
 * Purpose:
 * Owns the main state of the Smart AI DJ homepage.
 *
 * How this connects to the project:
 * Multiple components need the same session information: prompt, player state,
 * now-playing data, feedback, and optional reasoning. This store is the single
 * source of truth for that shared state.
 *
 * Engineering decision:
 * Components stay mostly visual. Business actions such as start, stop,
 * play/pause, feedback, and reasoning toggle are centralized here. This prevents
 * impossible UI states and makes future backend integration easier.
 */

const startupSteps = [
  "Understanding your vibe",
  "Finding matching song moments",
  "Planning the first transition",
  "Preparing the AI DJ session"
];

/** @type {import("../types.js").SessionState} */
const initialState = {
  status: APP_STATES.IDLE,
  prompt: "",
  currentStep: "",
  progress: 0,
  session: null,
  isPlaying: false,
  showReasoning: false,
  selectedFeedback: null,
  error: null
};

function createSessionStore() {
  const { subscribe, set, update } = writable(initialState);

  /** @type {import("../types.js").SessionState} */
  let latestState = initialState;

  // Keep a snapshot so async actions can safely read the latest prompt/session.
  subscribe((value) => {
    latestState = value;
  });

  return {
    subscribe,

    /**
     * Updates the user's vibe prompt.
     *
     * @param {string} prompt
     */
    setPrompt(prompt) {
      update((state) => ({
        ...state,
        prompt
      }));
    },

    /**
     * Starts the continuous AI DJ session.
     *
     * This replaces the old finite "Generate Mix" action. The session begins
     * with mock startup steps now; later these steps can reflect real backend
     * job progress.
     */
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
        showReasoning: false,
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

        const session = await startSessionMock({ prompt });

        update((state) => ({
          ...state,
          status: APP_STATES.PLAYING,
          currentStep: "Playing your vibe",
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
            "Something went wrong while starting the AI DJ. Try another vibe or choose a preset."
        }));
      }
    },

    /**
     * Toggles play/pause only while a session is active.
     *
     * Guarding here is important. Even if a component accidentally calls this
     * action after the session is stopped, the store refuses to create the
     * impossible state: status="stopped" with isPlaying=true.
     */
    togglePlay() {
      if (latestState.status !== APP_STATES.PLAYING) {
        return;
      }

      update((state) => ({
        ...state,
        isPlaying: !state.isPlaying
      }));
    },

    /**
     * Stops the current AI DJ session and moves the UI into a stopped state.
     *
     * For MVP, stopped sessions cannot be resumed. The user starts a new vibe
     * from the prompt composer instead. This keeps behavior simple and avoids
     * confusing play/resume edge cases.
     */
    async stop() {
      if (
        latestState.status !== APP_STATES.PLAYING &&
        latestState.status !== APP_STATES.BUFFERING_NEXT
      ) {
        return;
      }

      const sessionId = latestState.session?.id ?? null;
      await stopSessionMock({ sessionId });

      update((state) => ({
        ...state,
        status: APP_STATES.STOPPED,
        isPlaying: false,
        currentStep: "Stopped",
        progress: 0,
        selectedFeedback: null
      }));
    },

    /**
     * Stores simple user feedback.
     *
     * In the real product this becomes a personalization signal for future
     * generated chunks. For MVP, it is visual + logged by the mock API.
     *
     * @param {string} feedback
     */
    async sendFeedback(feedback) {
      if (latestState.status !== APP_STATES.PLAYING) {
        return;
      }

      const sessionId = latestState.session?.id ?? null;
      await sendFeedbackMock({ sessionId, feedback });

      update((state) => ({
        ...state,
        selectedFeedback: feedback
      }));
    },

    /**
     * Opens/closes the optional AI reasoning panel.
     *
     * Reasoning is hidden by default because the normal user experience should
     * feel like a clean music player, not an ML dashboard.
     */
    toggleReasoning() {
      if (!latestState.session) {
        return;
      }

      update((state) => ({
        ...state,
        showReasoning: !state.showReasoning
      }));
    },

    /**
     * Resets the home page to the first idle state.
     */
    reset() {
      set({ ...initialState });
    }
  };
}

export const sessionStore = createSessionStore();
