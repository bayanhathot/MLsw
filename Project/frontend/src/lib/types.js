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
 * @property {string} genre
 * @property {string} vibe
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
 * @property {'discussion'|'status'|'mix_share'} kind
 * @property {'public'|'friends'} visibility
 * @property {{id:number,title:string,prompt:string,coverUrl:string,ownerUsername:string,segmentCount:number}|null} mix
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
 * A normalized listener card used in search/discovery/friends lists.
 *
 * @typedef {Object} SocialUser
 * @property {number} id
 * @property {string} username
 * @property {string | null} displayName
 * @property {string | null} avatarUrl
 * @property {string | null} bio
 * @property {string[]} musicInterests
 * @property {number} friendCount
 * @property {number} mutualFriendCount
 * @property {string} relationshipStatus
 */

/**
 * Raw (snake_case) friend-request shapes as returned by the backend.
 *
 * @typedef {Object} FriendRequestOtherUser
 * @property {number} id
 * @property {string} username
 * @property {string | null} display_name
 * @property {string | null} avatar_url
 * @property {string | null} bio
 * @property {string[] | null} music_interests
 * @property {number} friend_count
 * @property {number} mutual_friend_count
 * @property {string} relationship_status
 *
 * @typedef {Object} FriendRequestEntry
 * @property {number} id
 * @property {string} sender_username
 * @property {string} receiver_username
 * @property {string} status
 * @property {string} created_at
 * @property {string | null} responded_at
 * @property {FriendRequestOtherUser | null} other_user
 */

/**
 * @typedef {Object} DirectMessage
 * @property {number} id
 * @property {number} sender_id
 * @property {string} sender_username
 * @property {number} recipient_id
 * @property {string} recipient_username
 * @property {string} body
 * @property {Record<string, any>[]} attachments
 * @property {string} created_at
 * @property {string | null} read_at
 */

/**
 * A normalized conversation-inbox row.
 *
 * @typedef {Object} Conversation
 * @property {string} username
 * @property {string | null} displayName
 * @property {string | null} avatarUrl
 * @property {string} lastMessage
 * @property {string} lastMessageAt
 * @property {number} unreadCount
 */

/**
 * @typedef {Object} AppNotification
 * @property {number} id
 * @property {string} kind
 * @property {string} message
 * @property {string | null} entity_type
 * @property {number | null} entity_id
 * @property {boolean} is_read
 * @property {string} created_at
 * @property {DirectMessage | null} direct_message
 */

/**
 * @typedef {Object} ProfileStats
 * @property {number} received_upvotes
 * @property {number} received_downvotes
 * @property {number} post_count
 * @property {number} comment_count
 */

/**
 * A safe, social-first public profile (`PublicProfileRead` on the backend).
 *
 * @typedef {Object} PublicProfile
 * @property {number} id
 * @property {string} username
 * @property {string | null} display_name
 * @property {string | null} avatar_url
 * @property {string | null} bio
 * @property {string[] | null} favorite_genres
 * @property {string} member_since
 * @property {ProfileStats} stats
 * @property {boolean} music_identity_public
 * @property {'private'|'friends'|'public'} music_identity_visibility
 * @property {number} friend_count
 * @property {number} mutual_friend_count
 * @property {number} published_mix_count
 * @property {string} relationship_status
 * @property {boolean} viewer_has_blocked
 */

/**
 * The Music Identity envelope returned for a public/friend viewer
 * (`PublicMusicIdentityRead` on the backend). The nested `music_identity`
 * blob stays loosely typed here; `MusicIdentityDashboard` treats it as
 * dynamic analytics data.
 *
 * @typedef {Object} PublicMusicIdentity
 * @property {string} username
 * @property {boolean} is_public
 * @property {Record<string, any> | null} music_identity
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

/**
 * Internal AI-DJ pipeline / Ollama debug panel (GET /debug/pipeline).
 *
 * @typedef {Object} PipelineDebugSession
 * @property {string} session_id
 * @property {string} prompt
 * @property {'playing'|'stopped'} status
 * @property {number | null} user_id
 * @property {string} retriever_name
 * @property {string} vibe_label
 * @property {string} updated_at
 * @property {Record<string, any> | null} trace
 * @property {boolean} has_prepared_next
 */

/**
 * @typedef {Object} PipelineDebugOllama
 * @property {boolean} configured
 * @property {boolean} reachable
 * @property {string | null} error
 * @property {string | null} configured_model
 * @property {string[]} loaded_models
 * @property {{ at: string | null, latency_ms: number | null, ok: boolean | null }} last_call
 */

/**
 * @typedef {Object} PipelineDebugState
 * @property {PipelineDebugOllama} ollama
 * @property {PipelineDebugSession[]} sessions
 */

export {};
