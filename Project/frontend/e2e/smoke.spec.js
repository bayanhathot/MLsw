import { expect, test } from '@playwright/test';

const authenticatedUser = {
	id: 1,
	username: 'test-listener',
	email: 'listener@example.com',
	is_active: true
};

const emptyIdentity = {
	is_public: false,
	visibility: 'private',
	period: 'all',
	summary: {
		total_listening_seconds: 0,
		top_artist: null,
		top_genre: null,
		top_vibe: null,
		artists_discovered: 0,
		tracks_discovered: 0,
		listening_contexts: 0,
		average_context_seconds: 0
	},
	artists: [],
	genres: [],
	vibes: [],
	top_tracks: [],
	time_of_day: [],
	listening_trend: [],
	recent_listening: [],
	listening_dna: {
		status: 'not_generated',
		label: null,
		summary: null,
		dimensions: [],
		version: null
	}
};

/**
 * Mock the API boundary while exercising the production Svelte UI.
 * @param {import('@playwright/test').Page} page
 * @param {{ authenticated?: boolean, promptShortcuts?: { prompt: string, count: number }[], onRealtimeSocket?: (socket: import('@playwright/test').WebSocketRoute) => void, sessionStartResponse?: Record<string, any>, catalogBatchJobResponse?: Record<string, any>, catalogBatchStatusResponse?: Record<string, any> }} options
 */
async function mockApi(
	page,
	{
		authenticated = false,
		promptShortcuts = [],
		onRealtimeSocket,
		sessionStartResponse,
		catalogBatchJobResponse,
		catalogBatchStatusResponse
	} = {}
) {
	const unexpectedRequests = [];

	await page.routeWebSocket('**/api/ws', (socket) => {
		socket.onMessage(() => {});
		onRealtimeSocket?.(socket);
	});

	await page.route('**/api/**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		let status = 200;
		let payload;

		if (path === '/api/sessions/start' && request.method() === 'POST' && sessionStartResponse) {
			payload = sessionStartResponse;
		} else if (
			path === '/api/catalog/tracks/batch-jobs' &&
			request.method() === 'POST' &&
			catalogBatchJobResponse
		) {
			status = 202;
			payload = catalogBatchJobResponse;
		} else if (
			path.startsWith('/api/catalog/tracks/batches/') &&
			request.method() === 'GET' &&
			catalogBatchStatusResponse
		) {
			payload = catalogBatchStatusResponse;
		} else if (path === '/api/auth/me') {
			status = authenticated ? 200 : 401;
			payload = authenticated ? authenticatedUser : { detail: 'Not authenticated.' };
		} else if (path === '/api/mixes/feed') {
			payload = [];
		} else if (path === '/api/posts/feed') {
			// Community requires a real session on every read (routers/forum.py),
			// unlike /api/mixes/feed -- mirror that here so a regression in the
			// frontend's own guest guard would surface as an unfixtured 401
			// instead of silently rendering an "empty feed" state.
			status = authenticated ? 200 : 401;
			payload = authenticated ? [] : { detail: 'Not authenticated.' };
		} else if (path === '/api/mixes/library') {
			payload = { owned: [], saved: [] };
		} else if (path === '/api/users/me/profile') {
			payload = {
				display_name: 'Test Listener',
				avatar_url: null,
				bio: 'Browser smoke fixture',
				favorite_genres: ['house']
			};
		} else if (path === '/api/users/me/preferences') {
			payload = [];
		} else if (path === '/api/users/me/prompt-shortcuts') {
			// PromptComposer only ever calls this for an authenticated identity
			// (see its $effect) -- reachable in the guest tests too only if
			// that scoping regresses, so it stays fixtured rather than
			// falling through to "unexpected".
			payload = promptShortcuts;
		} else if (path === '/api/users/me/music-identity') {
			payload = emptyIdentity;
		} else if (path === `/api/users/${authenticatedUser.username}/profile`) {
			payload = {
				id: 1,
				username: authenticatedUser.username,
				display_name: 'Test Listener',
				avatar_url: null,
				bio: 'Browser smoke fixture',
				favorite_genres: ['house'],
				member_since: '2026-08-01T00:00:00Z',
				stats: { received_upvotes: 0, received_downvotes: 0, post_count: 0, comment_count: 0 },
				music_identity_public: false,
				music_identity_visibility: 'private',
				friend_count: 0,
				mutual_friend_count: 0,
				published_mix_count: 0,
				relationship_status: 'self',
				viewer_has_blocked: false
			};
		} else if (path === '/api/notifications' || path === '/api/conversations') {
			payload = [];
		} else if (path === '/api/debug/pipeline') {
			// PipelineDebugPanel probes this on every page load, logged in or
			// not (no login required by design, see routers/debug.py) -- the
			// real backend 404s here whenever ENABLE_PIPELINE_DEBUG is off
			// (the default), so this mirrors that rather than treating it as
			// an unfixtured/unexpected call.
			status = 404;
			payload = { detail: 'Not found.' };
		} else {
			unexpectedRequests.push(`${request.method()} ${path}`);
			status = 501;
			payload = { detail: `No browser-test fixture for ${path}` };
		}

		await route.fulfill({
			status,
			contentType: 'application/json',
			body: JSON.stringify(payload)
		});
	});

	return unexpectedRequests;
}

test('public DJ and Discover routes render through navigation, with no Community link for a guest', async ({
	page
}) => {
	const unexpectedRequests = await mockApi(page);

	await page.goto('/');
	await expect(page.getByRole('heading', { name: /Your AI DJ/ })).toBeVisible();
	// Community is members-only end to end now (routers/forum.py and
	// routers/social.py require a real session on every read and write), so
	// the nav link is hidden entirely for a guest rather than present and
	// then failing/redirecting on click.
	await expect(page.getByRole('link', { name: 'Community' })).toHaveCount(0);

	await page.getByRole('link', { name: 'Discover' }).click();
	await expect(page).toHaveURL(/\/feed$/);
	await expect(page.getByRole('heading', { name: 'Discover mixes' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Community' })).toHaveCount(0);
	expect(unexpectedRequests).toEqual([]);
});

test('guest users are redirected away from protected routes', async ({ page }) => {
	const unexpectedRequests = await mockApi(page);

	await page.goto('/library');
	await expect(page).toHaveURL(/\/login$/);
	await expect(page.getByRole('heading', { name: 'Sign in.' })).toBeVisible();

	// Community requires a real session on every read/write (see
	// routers/forum.py) -- a guest hitting it directly by URL, not just via
	// the (already-hidden) nav link, must also bounce to /login rather than
	// render an empty/broken feed.
	await page.goto('/community');
	await expect(page).toHaveURL(/\/login$/);
	await expect(page.getByRole('heading', { name: 'Sign in.' })).toBeVisible();

	await page.goto('/upload');
	await expect(page).toHaveURL(/\/login$/);
	await expect(page.getByRole('heading', { name: 'Sign in.' })).toBeVisible();

	await page.goto('/profile');
	await expect(page).toHaveURL(/\/login$/);
	await expect(page.getByRole('heading', { name: 'Sign in.' })).toBeVisible();
	expect(unexpectedRequests).toEqual([]);
});

test('authenticated library, Music Identity profile, and messages load their API state', async ({
	page
}) => {
	const unexpectedRequests = await mockApi(page, { authenticated: true });

	await page.goto('/library');
	await expect(page.getByRole('heading', { name: 'Mix library' })).toBeVisible();
	await expect(page.getByText('No generated drafts yet.')).toBeVisible();

	await page.getByRole('link', { name: 'Your profile' }).click();
	await expect(page.getByRole('heading', { name: 'Test Listener' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Your Music Identity' })).toBeVisible();

	await page.getByRole('link', { name: 'Messages' }).click();
	await expect(page.getByRole('heading', { name: 'Messages' })).toBeVisible();
	await expect(page.getByText('No conversations yet')).toBeVisible();
	expect(unexpectedRequests).toEqual([]);
});

test('guest home page only shows the static preset shortcuts', async ({ page }) => {
	const unexpectedRequests = await mockApi(page);

	await page.goto('/');
	await expect(page.getByRole('heading', { name: /Your AI DJ/ })).toBeVisible();
	// The first five static presets fill every slot with no personalized
	// identity to draw from -- the sixth ("party warmup") never fits.
	await expect(page.getByRole('button', { name: 'deep work focus' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'chill and relax' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'party warmup' })).toHaveCount(0);
	expect(unexpectedRequests).toEqual([]);
});

test('auto-mix modes influence but never replace the user prompt', async ({ page }) => {
	const unexpectedRequests = await mockApi(page, {
		sessionStartResponse: {
			id: 'session-e2e-mode-influence',
			prompt: 'slow jazz for reading without vocals',
			mode: 'relaxation',
			now_playing: { title: 'Reading Track', artist: 'Test Artist' },
			audio_url: '/media/e2e-fixture-track.mp3',
			segments: [],
			reasoning: {}
		}
	});

	await page.goto('/');
	const prompt = page.getByPlaceholder(/emotional Arabic vocals/);

	// Selecting a mode with an empty composer must not manufacture a ready-made prompt.
	await page.getByRole('button', { name: 'Workout' }).click();
	await expect(prompt).toHaveValue('');
	await expect(page.getByRole('button', { name: /Start AI DJ/ })).toBeDisabled();

	// Changing the influence after typing must preserve the user's wording exactly.
	await prompt.fill('slow jazz for reading without vocals');
	await page.getByRole('button', { name: 'Relaxation' }).click();
	await expect(prompt).toHaveValue('slow jazz for reading without vocals');
	await expect(page.getByRole('button', { name: 'Relaxation' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);

	const startRequestPromise = page.waitForRequest(
		(request) =>
			new URL(request.url()).pathname === '/api/sessions/start' && request.method() === 'POST'
	);
	await page.getByRole('button', { name: /Start AI DJ/ }).click();
	const startRequest = await startRequestPromise;
	expect(startRequest.postDataJSON()).toEqual({
		prompt: 'slow jazz for reading without vocals',
		mode: 'relaxation'
	});
	expect(unexpectedRequests).toEqual([]);
});

test('authenticated home page shows a personalized shortcut chip ahead of the static presets', async ({
	page
}) => {
	const unexpectedRequests = await mockApi(page, {
		authenticated: true,
		promptShortcuts: [{ prompt: 'my usual gym flow', count: 5 }]
	});

	await page.goto('/');
	await expect(page.getByRole('heading', { name: /Your AI DJ/ })).toBeVisible();
	await expect(page.getByRole('button', { name: 'my usual gym flow' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'deep work focus' })).toBeVisible();
	// The personalized chip took one of the five slots, so the fifth static
	// preset that a guest would see is bumped out.
	await expect(page.getByRole('button', { name: 'chill and relax' })).toHaveCount(0);

	// Clicking a personalized chip behaves exactly like a static preset --
	// it fills the prompt box with the chip's own stored prompt text.
	await page.getByRole('button', { name: 'my usual gym flow' }).click();
	await expect(page.getByPlaceholder(/emotional Arabic vocals/)).toHaveValue('my usual gym flow');
	expect(unexpectedRequests).toEqual([]);
});

test('Community feed applies live post_created and post_deleted WS events with no reload', async ({
	page
}) => {
	/** @type {import('@playwright/test').WebSocketRoute | null} */
	let realtimeSocket = null;
	const unexpectedRequests = await mockApi(page, {
		authenticated: true,
		onRealtimeSocket: (socket) => {
			realtimeSocket = socket;
		}
	});

	await page.goto('/community');
	await expect(page.getByRole('heading', { name: 'Community' })).toBeVisible();
	await expect(page.getByText('No posts here yet. Start the conversation.')).toBeVisible();

	// realtimeSocket.js only opens /ws once authStore reports an
	// authenticated user, which itself only lands after /api/auth/me
	// resolves -- wait for the mocked handshake before pushing frames.
	await expect.poll(() => realtimeSocket !== null).toBe(true);

	const livePost = {
		id: 501,
		author_id: 2,
		author_username: 'other-listener',
		title: 'Live update',
		body: 'This arrived over the wire, no reload needed',
		is_anonymous: false,
		kind: 'status',
		visibility: 'public',
		mix: null,
		can_delete: false,
		score: 0,
		comment_count: 0,
		my_vote: 0,
		attachments: [],
		created_at: '2026-08-16T00:00:00Z'
	};
	await /** @type {import('@playwright/test').WebSocketRoute} */ (realtimeSocket).send(
		JSON.stringify({ channel: 'feed:status', type: 'post_created', data: livePost })
	);
	await expect(page.getByText('This arrived over the wire, no reload needed')).toBeVisible();

	await /** @type {import('@playwright/test').WebSocketRoute} */ (realtimeSocket).send(
		JSON.stringify({ channel: 'feed:status', type: 'post_deleted', data: { post_id: 501 } })
	);
	await expect(page.getByText('This arrived over the wire, no reload needed')).toHaveCount(0);

	expect(unexpectedRequests).toEqual([]);
});

test('the AI DJ player survives navigating away from the home route', async ({ page }) => {
	const unexpectedRequests = await mockApi(page, {
		sessionStartResponse: {
			id: 'session-e2e-persist',
			prompt: 'chill focus beats',
			now_playing: { title: 'Persistent Track', artist: 'Persistent Artist' },
			audio_url: '/media/e2e-fixture-track.mp3',
			segments: [],
			reasoning: {}
		}
	});

	await page.goto('/');
	const djPlayer = page.locator('section[aria-label="Cuemix AI DJ player"]');
	await expect(djPlayer).toBeHidden();
	await page.getByPlaceholder(/emotional Arabic vocals/).fill('chill focus beats');
	await page.getByRole('button', { name: /Start AI DJ/ }).click();

	await expect(djPlayer).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Persistent Track' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Keep this vibe' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'More energy' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Fewer vocals' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Smoother' })).toHaveCount(0);
	const audioSrcOnHome = await page.locator('audio.hidden-audio').getAttribute('src');
	expect(audioSrcOnHome).toContain('e2e-fixture-track.mp3');

	// DJPlayerCard renders from routes/+layout.svelte now, not
	// routes/+page.svelte -- navigating to a route that never renders it
	// itself must NOT unmount (and so silence) the player.
	await page.getByRole('link', { name: 'Discover' }).click();
	await expect(page).toHaveURL(/\/feed$/);
	await expect(page.getByRole('heading', { name: 'Persistent Track' })).toBeVisible();
	await expect(page.locator('audio.hidden-audio')).toHaveAttribute('src', audioSrcOnHome ?? '');

	// Auth pages should stay focused on authentication even if a global
	// player session is still mounted in the root layout.
	await page.goto('/login');
	await expect(djPlayer).toBeHidden();

	expect(unexpectedRequests).toEqual([]);
});

test('uploading a song through the bulk upload page shows it as completed', async ({ page }) => {
	const unexpectedRequests = await mockApi(page, {
		authenticated: true,
		catalogBatchJobResponse: {
			job_id: 'job-e2e-1',
			batch_id: 'batch-e2e',
			filename: 'song.mp3',
			status: 'queued',
			priority: 5,
			track: null,
			error: null
		},
		catalogBatchStatusResponse: {
			batch_id: 'batch-e2e',
			total: 1,
			queued: 0,
			validating: 0,
			storing: 0,
			analyzing: 0,
			completed: 1,
			failed: 0,
			cancelled: 0,
			jobs: [
				{
					job_id: 'job-e2e-1',
					batch_id: 'batch-e2e',
					filename: 'song.mp3',
					status: 'completed',
					priority: 5,
					track: {
						id: 1,
						title: 'E2E Song',
						artist: 'E2E Artist',
						album: 'E2E Album',
						genre: null,
						lyrics: null,
						visibility: 'private',
						duration_seconds: 180,
						analysis_status: 'pending',
						audio_url: '/api/catalog/tracks/1/audio',
						cover_url: null,
						created_at: '2026-08-17T00:00:00Z'
					},
					error: null
				}
			]
		}
	});

	await page.goto('/upload');
	await expect(page.getByRole('heading', { name: 'Upload music' })).toBeVisible();

	await page
		.locator('input[type="file"]')
		.first()
		.setInputFiles({
			name: 'song.mp3',
			mimeType: 'audio/mpeg',
			buffer: Buffer.from('ID3 fake mp3 bytes for e2e')
		});
	await page.getByLabel('Title').fill('E2E Song');
	await page.getByLabel('Artist').fill('E2E Artist');
	await page.getByLabel('Album').fill('E2E Album');
	await page.getByRole('button', { name: 'Upload All' }).click();

	await expect(page.getByText('Uploaded')).toBeVisible();
	await expect(page.getByText('Batch finished')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Upload more songs' })).toBeVisible();

	expect(unexpectedRequests).toEqual([]);
});
