/**
 * Legal frontend session states.
 *
 * idle:
 * User has not started the AI DJ yet.
 *
 * starting:
 * The app is preparing the first session.
 *
 * playing:
 * AI DJ session is active.
 *
 * buffering_next:
 * Future state for preparing the next audio chunk.
 *
 * stopped:
 * User stopped the AI DJ session.
 *
 * error:
 * Something failed.
 *
 * @typedef {"idle" | "starting" | "playing" | "buffering_next" | "stopped" | "error"} AppStatus
 */

/**
 * Preset chip shown in the prompt composer.
 *
 * @typedef {Object} Preset
 * @property {string} label
 * @property {string} prompt
 */

/**
 * User-facing metadata for the currently playing song moment.
 *
 * @typedef {Object} NowPlaying
 * @property {string} title
 * @property {string} artist
 * @property {string} album
 * @property {string} coverUrl
 * @property {string} vibeLabel
 */

/**
 * Human-readable AI explanation.
 *
 * This is for demo/explainability only.
 * It should not expose raw model scores in the normal UI.
 *
 * @typedef {Object} AIReasoning
 * @property {string} selectedMoment
 * @property {string} transitionPlan
 * @property {string} nextDirection
 */

/**
 * Active AI DJ session returned by the backend/mock API.
 *
 * @typedef {Object} Session
 * @property {string} id
 * @property {string} vibeLabel
 * @property {NowPlaying} nowPlaying
 * @property {string} audioUrl
 * @property {AIReasoning} reasoning
 */

/**
 * Central frontend state for the AI DJ session.
 *
 * @typedef {Object} SessionState
 * @property {AppStatus} status
 * @property {string} prompt
 * @property {number} progress
 * @property {string} currentStep
 * @property {Session | null} session
 * @property {boolean} isPlaying
 * @property {string | null} selectedFeedback
 * @property {boolean} reasoningOpen
 * @property {string | null} error
 */

export {};