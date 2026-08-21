import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const apiMocks = vi.hoisted(() => ({
	startSession: vi.fn(),
	sendFeedback: vi.fn(),
	advanceSession: vi.fn(),
	stopSession: vi.fn(),
	prepareNext: vi.fn()
}));

vi.mock('../services/sessionApi.js', () => apiMocks);

const { sessionStore } = await import('./sessionStore.js');

/** @param {Partial<import('../types.js').Session>} [overrides] */
function makeSession(overrides = {}) {
	return {
		id: 'session-1',
		prompt: 'chill lofi beats',
		mode: null,
		vibeLabel: 'Deep work focus',
		nowPlaying: {
			title: 'Track One',
			artist: 'Artist One',
			album: 'Cuemix mix',
			coverUrl: '',
			vibeLabel: 'Deep work focus',
			role: 'Now playing'
		},
		audioUrl: '/api/media/renders/one.wav',
		reasoning: { selectedMoment: '', transitionPlan: '', nextDirection: '' },
		segments: [],
		selectedFeedback: null,
		...overrides
	};
}

function deferred() {
	/** @type {(value: any) => void} */
	let resolve = () => {};
	const promise = new Promise((res) => {
		resolve = res;
	});
	return { promise, resolve };
}

async function startPlayingSession() {
	apiMocks.startSession.mockResolvedValueOnce(makeSession());
	sessionStore.setPrompt('chill lofi beats');
	const ok = await sessionStore.start();
	expect(ok).toBe(true);
}

beforeEach(() => {
	apiMocks.startSession.mockReset();
	apiMocks.sendFeedback.mockReset();
	apiMocks.advanceSession.mockReset();
	apiMocks.stopSession.mockReset();
	apiMocks.prepareNext.mockReset();
	sessionStore.reset();
});

afterEach(() => {
	vi.restoreAllMocks();
});

describe('sessionStore.start (change vibe while already playing)', () => {
	it('sends the selected literal mode and retains the server-confirmed mode', async () => {
		apiMocks.startSession.mockResolvedValueOnce(makeSession({ mode: 'party' }));
		sessionStore.setPrompt('music for tonight');
		sessionStore.setMode('party');

		const ok = await sessionStore.start();

		expect(ok).toBe(true);
		expect(apiMocks.startSession).toHaveBeenCalledWith(
			expect.objectContaining({ prompt: 'music for tonight', mode: 'party' })
		);
		expect(get(sessionStore).mode).toBe('party');
	});

	it('keeps the current session/playback untouched while the new vibe is loading', async () => {
		await startPlayingSession();
		const before = get(sessionStore);

		const startCall = deferred();
		apiMocks.startSession.mockReturnValueOnce(startCall.promise);
		apiMocks.stopSession.mockResolvedValueOnce(undefined);
		sessionStore.setPrompt('energetic techno');
		const startPromise = sessionStore.start();

		const midFlight = get(sessionStore);
		expect(midFlight.session).toBe(before.session);
		expect(midFlight.isPlaying).toBe(before.isPlaying);
		expect(midFlight.playbackRequested).toBe(before.playbackRequested);
		expect(midFlight.isPlaybackBuffering).toBe(before.isPlaybackBuffering);
		expect(midFlight.status).toBe('playing');
		expect(midFlight.isChangingVibe).toBe(true);

		startCall.resolve(makeSession({ id: 'session-2', prompt: 'energetic techno' }));
		await startPromise;
	});

	it('swaps to the new session and requests playback once it arrives', async () => {
		await startPlayingSession();
		apiMocks.startSession.mockResolvedValueOnce(makeSession({ id: 'session-2' }));
		apiMocks.stopSession.mockResolvedValueOnce(undefined);
		sessionStore.setPrompt('energetic techno');

		const ok = await sessionStore.start();

		expect(ok).toBe(true);
		const after = get(sessionStore);
		expect(after.session?.id).toBe('session-2');
		expect(after.status).toBe('playing');
		expect(after.playbackRequested).toBe(true);
		expect(after.isPlaybackBuffering).toBe(true);
		expect(after.isChangingVibe).toBe(false);
	});

	it('keeps the old session playing (not ERROR) when the new vibe fails to load', async () => {
		await startPlayingSession();
		const before = get(sessionStore);
		apiMocks.startSession.mockRejectedValueOnce(new Error('audius unreachable'));
		sessionStore.setPrompt('energetic techno');

		const ok = await sessionStore.start();

		expect(ok).toBe(false);
		const after = get(sessionStore);
		expect(after.status).toBe('playing');
		expect(after.session).toBe(before.session);
		expect(after.playbackRequested).toBe(before.playbackRequested);
		expect(after.isChangingVibe).toBe(false);
		expect(after.error).toContain('audius unreachable');
	});

	it('still resets straight to the loading state for a true fresh start (nothing playing yet)', async () => {
		sessionStore.setPrompt('chill lofi beats');
		const startCall = deferred();
		apiMocks.startSession.mockReturnValueOnce(startCall.promise);
		const startPromise = sessionStore.start();

		const midFlight = get(sessionStore);
		expect(midFlight.status).toBe('starting');
		expect(midFlight.session).toBeNull();
		expect(midFlight.isChangingVibe).toBe(false);

		startCall.resolve(makeSession());
		await startPromise;
	});
});

describe('sessionStore.prepareNext', () => {
	it('returns the prepared audioUrl when nothing interrupts it', async () => {
		await startPlayingSession();
		apiMocks.prepareNext.mockResolvedValueOnce({
			prepared: true,
			audioUrl: '/api/media/renders/two.wav'
		});

		const preparedUrl = await sessionStore.prepareNext();

		expect(preparedUrl).toBe('/api/media/renders/two.wav');
		expect(apiMocks.prepareNext).toHaveBeenCalledWith(
			expect.objectContaining({ sessionId: 'session-1' })
		);
	});

	it('does not mutate session state on success -- it only reports the URL', async () => {
		await startPlayingSession();
		apiMocks.prepareNext.mockResolvedValueOnce({
			prepared: true,
			audioUrl: '/api/media/renders/two.wav'
		});
		const before = get(sessionStore);

		await sessionStore.prepareNext();

		const after = get(sessionStore);
		expect(after.session).toBe(before.session);
		expect(after.isFeedbackPending).toBe(false);
	});

	it('resolves to null instead of throwing when the request fails', async () => {
		await startPlayingSession();
		apiMocks.prepareNext.mockRejectedValueOnce(new Error('network down'));

		await expect(sessionStore.prepareNext()).resolves.toBeNull();
	});

	// Mirrors the race protection advance() already has against sendFeedback
	// (see the comment on advance() in sessionStore.js): prepareNext() shares
	// the same feedbackVersion counter, so a result that lands after feedback
	// has already moved the version on must be discarded, not applied.
	it('discards a prepareNext() result that resolves after feedback has moved feedbackVersion on', async () => {
		await startPlayingSession();

		const prepareCall = deferred();
		apiMocks.prepareNext.mockReturnValueOnce(prepareCall.promise);
		apiMocks.sendFeedback.mockResolvedValueOnce(makeSession({ selectedFeedback: 'More energy' }));

		const prepareNextPromise = sessionStore.prepareNext();
		// Feedback lands and fully resolves before the in-flight prepare does.
		const feedbackOk = await sessionStore.sendFeedback('More energy');
		expect(feedbackOk).toBe(true);
		expect(get(sessionStore).selectedFeedback).toBe('More energy');

		// The prepare call finally resolves, after feedbackVersion has moved on.
		prepareCall.resolve({ prepared: true, audioUrl: '/api/media/renders/stale.wav' });
		const preparedUrl = await prepareNextPromise;

		expect(preparedUrl).toBeNull();
		// Feedback's own result must still be intact -- not clobbered by the
		// late-arriving, now-stale prepare resolution.
		expect(get(sessionStore).selectedFeedback).toBe('More energy');
	});

	it('is a no-op when a coach feedback/advance call is already pending', async () => {
		await startPlayingSession();
		const feedbackCall = deferred();
		apiMocks.sendFeedback.mockReturnValueOnce(feedbackCall.promise);

		const feedbackPromise = sessionStore.sendFeedback('More energy');
		expect(get(sessionStore).isFeedbackPending).toBe(true);

		const preparedUrl = await sessionStore.prepareNext();
		expect(preparedUrl).toBeNull();
		expect(apiMocks.prepareNext).not.toHaveBeenCalled();

		feedbackCall.resolve(makeSession({ selectedFeedback: 'More energy' }));
		await feedbackPromise;
	});
});
