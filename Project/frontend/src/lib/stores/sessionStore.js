/** Session lifecycle and media intent for the main Cuemix player. */

import { writable } from 'svelte/store';

import { APP_STATES } from '../constants/appStates.js';
import {
	advanceSession as apiAdvanceSession,
	prepareNext as apiPrepareNext,
	sendFeedback as apiSendFeedback,
	startSession as apiStartSession,
	stopSession as apiStopSession
} from '../services/sessionApi.js';

/** @returns {import('../types.js').SessionState} */
function initialState() {
	return {
		status: APP_STATES.IDLE,
		prompt: '',
		mode: null,
		currentStep: '',
		progress: 0,
		session: null,
		isPlaying: false,
		playbackRequested: false,
		isPlaybackBuffering: false,
		hasEnded: false,
		isStopping: false,
		isChangingVibe: false,
		isFeedbackPending: false,
		pendingFeedback: null,
		reasoningOpen: false,
		selectedFeedback: null,
		playbackError: null,
		error: null
	};
}

/** @param {unknown} error */
function messageFrom(error) {
	return error instanceof Error ? error.message : 'An unexpected error occurred.';
}

function createSessionStore() {
	const { subscribe, set, update } = writable(initialState());
	/** @type {import('../types.js').SessionState} */
	let latestState = initialState();
	let lifecycleVersion = 0;
	let feedbackVersion = 0;
	/** @type {AbortController | null} */
	let startController = null;
	/** @type {AbortController | null} */
	let stopController = null;
	/** @type {AbortController | null} */
	let feedbackController = null;

	subscribe((value) => {
		latestState = value;
	});

	function abortPendingRequests() {
		startController?.abort();
		stopController?.abort();
		feedbackController?.abort();
		startController = null;
		stopController = null;
		feedbackController = null;
	}

	/**
	 * Continues the session onto its next track/segment with no user input --
	 * called automatically from mediaEnded() below. Shares sendFeedback's
	 * controller/version slot on purpose: explicit coaching feedback sent
	 * while an advance is in flight bumps feedbackVersion, so the advance's
	 * result is discarded when it lands and feedback's own result wins --
	 * coaching still interrupts and redirects mid-loop, exactly as it
	 * already does between two feedback calls.
	 */
	async function advance() {
		if (
			latestState.status !== APP_STATES.PLAYING ||
			latestState.isFeedbackPending ||
			!latestState.session?.id
		) {
			return false;
		}

		const sessionId = latestState.session.id;
		const requestVersion = ++feedbackVersion;
		const lifecycleAtRequest = lifecycleVersion;
		feedbackController = new AbortController();
		update((state) => ({
			...state,
			isFeedbackPending: true,
			currentStep: 'Finding the next track'
		}));

		try {
			const session = await apiAdvanceSession({ sessionId, signal: feedbackController.signal });
			if (
				requestVersion !== feedbackVersion ||
				latestState.session?.id !== sessionId ||
				lifecycleAtRequest !== lifecycleVersion
			) {
				return false;
			}

			update((state) => ({
				...state,
				session,
				isFeedbackPending: false,
				pendingFeedback: null,
				hasEnded: false,
				playbackRequested: true,
				isPlaybackBuffering: true,
				currentStep: 'Zone active'
			}));
			return true;
		} catch (error) {
			if (requestVersion === feedbackVersion && latestState.session?.id === sessionId) {
				update((state) => ({
					...state,
					isFeedbackPending: false,
					pendingFeedback: null,
					hasEnded: true,
					playbackError: `Could not advance to the next track: ${messageFrom(error)}`
				}));
			}
			return false;
		} finally {
			feedbackController = null;
		}
	}

	/**
	 * Best-effort prefetch of the session's next track/segment
	 * (PHASE_C_PREFETCH_DESIGN.md section 4.1), fired speculatively from
	 * DJPlayerCard as the current segment nears its end. Shares advance()'s
	 * feedbackVersion/feedbackController slot on purpose, for the same
	 * reason advance() shares it with sendFeedback (see advance()'s comment
	 * above): if coaching feedback lands before this resolves, feedbackVersion
	 * has already moved on and this result is discarded, exactly like a
	 * stale advance() result would be. Never touches session state on
	 * success -- the backend already persisted the prepared item
	 * server-side; this only hands back the next audioUrl for DJPlayerCard's
	 * optional preload step, and swallows any failure silently (never
	 * surfaced as a user-facing error, unlike advance/sendFeedback).
	 *
	 * @returns {Promise<string | null>}
	 */
	async function prepareNext() {
		if (
			latestState.status !== APP_STATES.PLAYING ||
			latestState.isFeedbackPending ||
			!latestState.session?.id
		) {
			return null;
		}

		const sessionId = latestState.session.id;
		const requestVersion = ++feedbackVersion;
		const lifecycleAtRequest = lifecycleVersion;
		feedbackController = new AbortController();

		try {
			const { audioUrl } = await apiPrepareNext({
				sessionId,
				signal: feedbackController.signal
			});
			if (
				requestVersion !== feedbackVersion ||
				latestState.session?.id !== sessionId ||
				lifecycleAtRequest !== lifecycleVersion
			) {
				return null;
			}
			return audioUrl;
		} catch {
			return null;
		} finally {
			feedbackController = null;
		}
	}

	return {
		subscribe,

		/** @param {string} prompt */
		setPrompt(prompt) {
			update((state) => ({ ...state, prompt }));
		},

		/** @param {import('../types.js').AutoMixMode | null} mode */
		setMode(mode) {
			update((state) => ({ ...state, mode }));
		},

		async start() {
			const prompt = latestState.prompt.trim();
			const mode = latestState.mode;
			if (!prompt || latestState.status === APP_STATES.STARTING) {
				return false;
			}

			// "Change vibe" reuses this same start() -- when a session is already
			// playing, the currently-audible track must keep playing right up
			// until the new vibe's session actually arrives (never an
			// interruption just because a new prompt was submitted). A true
			// fresh start (nothing playing yet) still resets straight to the
			// loading state, since there's nothing to preserve.
			const isChangingVibeWhilePlaying =
				latestState.status === APP_STATES.PLAYING && Boolean(latestState.session);
			const previousSessionId = latestState.session?.id;
			abortPendingRequests();
			const requestVersion = ++lifecycleVersion;
			startController = new AbortController();

			update((state) => ({
				...state,
				prompt,
				currentStep: 'Creating your mix',
				playbackError: null,
				error: null,
				isChangingVibe: isChangingVibeWhilePlaying,
				...(isChangingVibeWhilePlaying
					? {}
					: {
							status: APP_STATES.STARTING,
							progress: 20,
							session: null,
							isPlaying: false,
							playbackRequested: false,
							isPlaybackBuffering: false,
							hasEnded: false,
							selectedFeedback: null
						}),
				isStopping: false,
				isFeedbackPending: false,
				pendingFeedback: null,
				reasoningOpen: false
			}));

			try {
				const session = await apiStartSession({ prompt, mode, signal: startController.signal });
				if (requestVersion !== lifecycleVersion) {
					return false;
				}

				if (!session.id || (!session.audioUrl && !session.segments.some((item) => item.audioUrl))) {
					throw new Error('The session did not include playable audio.');
				}

				update((state) => ({
					...state,
					mode: session.mode,
					status: APP_STATES.PLAYING,
					currentStep: 'Ready to play',
					progress: 100,
					session,
					playbackRequested: true,
					isPlaying: false,
					isPlaybackBuffering: true,
					hasEnded: false,
					selectedFeedback: null,
					isChangingVibe: false
				}));

				if (previousSessionId && previousSessionId !== session.id) {
					void apiStopSession({ sessionId: previousSessionId }).catch(() => {});
				}

				return true;
			} catch (error) {
				if (requestVersion !== lifecycleVersion) {
					return false;
				}

				update((state) => ({
					...state,
					isChangingVibe: false,
					...(isChangingVibeWhilePlaying
						? {
								// The old vibe is still perfectly fine -- keep it playing
								// rather than dropping into a dead ERROR state just because
								// the *new* vibe failed to load.
								status: APP_STATES.PLAYING,
								currentStep: 'Zone active',
								error: `Could not update the vibe: ${messageFrom(error)}`
							}
						: {
								status: APP_STATES.ERROR,
								currentStep: 'Unable to start',
								progress: 0,
								isPlaying: false,
								playbackRequested: false,
								isPlaybackBuffering: false,
								error: messageFrom(error)
							})
				}));
				return false;
			} finally {
				if (requestVersion === lifecycleVersion) {
					startController = null;
				}
			}
		},

		togglePlay() {
			if (
				latestState.status !== APP_STATES.PLAYING ||
				latestState.isStopping ||
				!latestState.session
			) {
				return;
			}

			const shouldPlay = !(latestState.isPlaying || latestState.playbackRequested);
			update((state) => ({
				...state,
				playbackRequested: shouldPlay,
				hasEnded: shouldPlay ? false : state.hasEnded,
				playbackError: null
			}));
		},

		async stop() {
			if (
				latestState.status !== APP_STATES.PLAYING ||
				latestState.isStopping ||
				!latestState.session?.id
			) {
				return false;
			}

			const sessionId = latestState.session.id;
			const requestVersion = lifecycleVersion;
			feedbackVersion += 1;
			feedbackController?.abort();
			feedbackController = null;
			stopController = new AbortController();
			update((state) => ({
				...state,
				isStopping: true,
				isFeedbackPending: false,
				pendingFeedback: null,
				playbackRequested: false,
				error: null
			}));

			try {
				await apiStopSession({ sessionId, signal: stopController.signal });
				if (requestVersion !== lifecycleVersion || latestState.session?.id !== sessionId) {
					return false;
				}

				update((state) => ({
					...state,
					status: APP_STATES.STOPPED,
					isPlaying: false,
					playbackRequested: false,
					isPlaybackBuffering: false,
					isStopping: false,
					currentStep: 'Zone ended',
					progress: 0,
					selectedFeedback: null
				}));
				return true;
			} catch (error) {
				if (requestVersion === lifecycleVersion) {
					update((state) => ({
						...state,
						isStopping: false,
						error: `Could not stop the session: ${messageFrom(error)}`
					}));
				}
				return false;
			} finally {
				stopController = null;
			}
		},

		/** @param {string} feedback */
		async sendFeedback(feedback) {
			if (
				latestState.status !== APP_STATES.PLAYING ||
				latestState.isFeedbackPending ||
				!latestState.session?.id
			) {
				return false;
			}

			const sessionId = latestState.session.id;
			const requestVersion = ++feedbackVersion;
			const lifecycleAtRequest = lifecycleVersion;
			feedbackController = new AbortController();
			update((state) => ({
				...state,
				isFeedbackPending: true,
				pendingFeedback: feedback,
				error: null
			}));

			try {
				const session = await apiSendFeedback({
					sessionId,
					feedback,
					signal: feedbackController.signal
				});
				if (
					requestVersion !== feedbackVersion ||
					latestState.session?.id !== sessionId ||
					lifecycleAtRequest !== lifecycleVersion
				) {
					return false;
				}

				update((state) => ({
					...state,
					session,
					selectedFeedback: feedback,
					isFeedbackPending: false,
					pendingFeedback: null
				}));
				return true;
			} catch (error) {
				if (requestVersion === feedbackVersion && latestState.session?.id === sessionId) {
					update((state) => ({
						...state,
						isFeedbackPending: false,
						pendingFeedback: null,
						error: `Could not send feedback: ${messageFrom(error)}`
					}));
				}
				return false;
			} finally {
				feedbackController = null;
			}
		},

		mediaPlaying() {
			update((state) => ({
				...state,
				isPlaying: true,
				playbackRequested: true,
				isPlaybackBuffering: false,
				hasEnded: false,
				currentStep: 'Zone active',
				playbackError: null
			}));
		},

		mediaPaused() {
			update((state) => ({ ...state, isPlaying: false, isPlaybackBuffering: false }));
		},

		mediaWaiting() {
			if (latestState.playbackRequested) {
				update((state) => ({
					...state,
					isPlaybackBuffering: true,
					currentStep: 'Buffering audio'
				}));
			}
		},

		mediaReady() {
			update((state) => ({ ...state, isPlaybackBuffering: false }));
		},

		mediaEnded() {
			update((state) => ({
				...state,
				isPlaying: false,
				playbackRequested: false,
				isPlaybackBuffering: false,
				hasEnded: true,
				currentStep: 'Session finished'
			}));
			// Continuous session: keep going onto the next track with no user
			// input required, unless something (stop, a new prompt) already
			// ended the session by the time this resolves -- advance() itself
			// re-checks status/session id before applying its result.
			void advance();
		},

		advance,
		prepareNext,

		/** @param {string} message */
		mediaError(message) {
			update((state) => ({
				...state,
				isPlaying: false,
				playbackRequested: false,
				isPlaybackBuffering: false,
				playbackError: message
			}));
		},

		toggleReasoning() {
			if (latestState.session) {
				update((state) => ({ ...state, reasoningOpen: !state.reasoningOpen }));
			}
		},

		clearError() {
			update((state) => ({ ...state, error: null, playbackError: null }));
		},

		reset() {
			lifecycleVersion += 1;
			feedbackVersion += 1;
			abortPendingRequests();
			set(initialState());
		}
	};
}

export const sessionStore = createSessionStore();
