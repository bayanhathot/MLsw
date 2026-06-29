/**
 * File: src/lib/constants/appStates.js
 * Purpose: Single source of truth for allowed frontend session states.
 * What it does:
 * - Defines all legal UI states used by the store and components.
 * - Prevents typo bugs by avoiding raw strings spread across the app.
 * - Documents the lifecycle of an AI DJ session: idle -> starting -> playing -> buffering_next -> stopped/error.
 */

/**
 * Purpose:
 * Defines the only valid high-level states for the Smart AI DJ frontend session.
 *
 * How this connects to the project:
 * The product is a continuous AI DJ experience, not a fixed-duration generated
 * file. These states describe a session lifecycle: start, play, prepare more,
 * stop, or fail.
 *
 * Engineering decision:
 * Keeping states in one central constant file prevents random string values from
 * spreading across the codebase. The JSDoc literal type makes VS Code understand
 * that APP_STATES.IDLE is exactly "idle", not just any string.
 *
 * @type {{
 *   IDLE: "idle",
 *   STARTING: "starting",
 *   PLAYING: "playing",
 *   BUFFERING_NEXT: "buffering_next",
 *   STOPPED: "stopped",
 *   ERROR: "error"
 * }}
 */
export const APP_STATES = {
  IDLE: "idle",
  STARTING: "starting",
  PLAYING: "playing",
  BUFFERING_NEXT: "buffering_next",
  STOPPED: "stopped",
  ERROR: "error"
};
