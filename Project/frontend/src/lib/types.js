// cSpell:ignore Zonix explainability

/**
 * @typedef {"idle" | "starting" | "playing" | "buffering_next" | "stopped" | "error"} AppStatus
 */

/**
 * @typedef {Object} Preset
 * @property {string} label
 * @property {string} prompt
 */

/**
 * User-facing metadata for the current Zonix moment.
 *
 * @typedef {Object} NowPlaying
 * @property {string} title
 * @property {string} artist
 * @property {string} album
 * @property {string} coverUrl
 * @property {string} vibeLabel
 * @property {string} role
 */

/**
 * Optional human-readable explanation for demos and lecturer Q&A.
 * Keep raw model scores out of the main user interface.
 *
 * @typedef {Object} AIReasoning
 * @property {string} selectedMoment
 * @property {string} transitionPlan
 * @property {string} nextDirection
 */

/**
 * Active Zonix session returned by the backend/mock API.
 *
 * @typedef {Object} Session
 * @property {string} id
 * @property {string} prompt
 * @property {string} vibeLabel
 * @property {NowPlaying} nowPlaying
 * @property {string} audioUrl
 * @property {AIReasoning} reasoning
 */

/**
 * Central frontend state for the Zonix session.
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
