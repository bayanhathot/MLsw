/** Session lifecycle and media intent for the main Zonix player. */

import { writable } from 'svelte/store';

import { APP_STATES } from '../constants/appStates.js';
import {
	sendFeedback as apiSendFeedback,
	startSession as apiStartSession,
	stopSession as apiStopSession
} from '../services/sessionApi.js';

/** @returns {import('../types.js').SessionState} */
function initialState() {
	return {
		status: APP_STATES.IDLE,
		prompt: '',
		currentStep: '',
		progress: 0,
		session: null,
		isPlaying: false,
		playbackRequested: false,
		isPlaybackBuffering: false,
		hasEnded: false,
		isStopping: false,
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

	return {
		subscribe,

		/** @param {string} prompt */
		setPrompt(prompt) {
			update((state) => ({ ...state, prompt }));
		},

		async start() {
			const prompt = latestState.prompt.trim();
			if (!prompt || latestState.status === APP_STATES.STARTING) {
				return false;
			}

			const previousSessionId = latestState.session?.id;
			abortPendingRequests();
			const requestVersion = ++lifecycleVersion;
			startController = new AbortController();

			update((state) => ({
				...state,
				prompt,
				status: APP_STATES.STARTING,
				currentStep: 'Creating your mix',
				progress: 20,
				session: null,
				isPlaying: false,
				playbackRequested: false,
				isPlaybackBuffering: false,
				hasEnded: false,
				isStopping: false,
				isFeedbackPending: false,
				pendingFeedback: null,
				reasoningOpen: false,
				selectedFeedback: null,
				playbackError: null,
				error: null
			}));

			try {
				const session = await apiStartSession({ prompt, signal: startController.signal });
				if (requestVersion !== lifecycleVersion) {
					return false;
				}

				if (!session.id || (!session.audioUrl && !session.segments.some((item) => item.audioUrl))) {
					throw new Error('The session did not include playable audio.');
				}

				update((state) => ({
					...state,
					status: APP_STATES.PLAYING,
					currentStep: 'Ready to play',
					progress: 100,
					session,
					playbackRequested: true,
					isPlaying: false,
					isPlaybackBuffering: true
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
					status: APP_STATES.ERROR,
					currentStep: 'Unable to start',
					progress: 0,
					isPlaying: false,
					playbackRequested: false,
					isPlaybackBuffering: false,
					error: messageFrom(error)
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
		},

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
