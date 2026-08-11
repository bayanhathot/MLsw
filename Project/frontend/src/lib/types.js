/**
 * File: src/lib/types.js
 * Purpose: JSDoc type definitions shared across the JavaScript frontend.
 * What it does:
 * - Documents the expected shape of app states, presets, now-playing metadata, AI reasoning, sessions, and store state.
 * - Gives VS Code/Svelte language tools better autocomplete and type checking without converting the project to TypeScript.
 * - Acts as a contract between frontend mock data and the future backend API.
 */

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
 * @property {SessionSegment[]} segments
 * @property {string | null} selectedFeedback
 */

/**
 * A playable segment. The frontend uses camelCase regardless of the backend's
 * serialization style.
 *
 * @typedef {Object} SessionSegment
 * @property {number|string} id
 * @property {number} position
 * @property {string} title
 * @property {string} artist
 * @property {string} audioUrl
 * @property {string} coverUrl
 * @property {number} startSecond
 * @property {number} endSecond
 * @property {string} transitionToNext
 * @property {string} source
 * @property {string} sourceTrackId
 */

/**
 * A persistent draft or published community mix.
 *
 * @typedef {Object} MixOwner
 * @property {number} id
 * @property {string} username
 *
 * @typedef {Object} Mix
 * @property {number} id
 * @property {string} sessionId
 * @property {string} title
 * @property {string} prompt
 * @property {string | null} description
 * @property {string} coverUrl
 * @property {'draft' | 'published'} status
 * @property {string} createdAt
 * @property {string | null} publishedAt
 * @property {SessionSegment[]} segments
 * @property {MixOwner | null} owner
 * @property {number} likeCount
 * @property {boolean} isLiked
 * @property {boolean} isSaved
 */

/**
 * @typedef {Object} ForumAttachment
 * @property {number} id
 * @property {string} kind
 * @property {string} filename
 * @property {string} contentType
 * @property {string} url
 * @property {number} sizeBytes
 *
 * @typedef {Object} ForumPost
 * @property {number} id
 * @property {number | null} authorId
 * @property {string} authorUsername
 * @property {string} title
 * @property {string} body
 * @property {boolean} isAnonymous
 * @property {boolean} canDelete
 * @property {number} score
 * @property {number} commentCount
 * @property {number} myVote
 * @property {ForumAttachment[]} attachments
 * @property {string} createdAt
 *
 * @typedef {Object} ForumComment
 * @property {number} id
 * @property {number | null} authorId
 * @property {string} authorUsername
 * @property {string} body
 * @property {boolean} isAnonymous
 * @property {boolean} canDelete
 * @property {number} score
 * @property {number} myVote
 * @property {ForumAttachment[]} attachments
 * @property {string} createdAt
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
 * @property {boolean} playbackRequested
 * @property {boolean} isPlaybackBuffering
 * @property {boolean} hasEnded
 * @property {boolean} isStopping
 * @property {boolean} isFeedbackPending
 * @property {string | null} pendingFeedback
 * @property {string | null} selectedFeedback
 * @property {boolean} reasoningOpen
 * @property {string | null} playbackError
 * @property {string | null} error
 */

export {};
