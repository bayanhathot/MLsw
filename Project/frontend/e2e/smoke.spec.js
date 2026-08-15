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
 * @param {{ authenticated?: boolean }} options
 */
async function mockApi(page, { authenticated = false } = {}) {
	const unexpectedRequests = [];

	await page.routeWebSocket('**/api/ws/notifications', (socket) => {
		socket.onMessage(() => {});
	});
	await page.routeWebSocket('**/api/posts/ws/community', (socket) => {
		socket.onMessage(() => {});
	});

	await page.route('**/api/**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		let status = 200;
		let payload;

		if (path === '/api/auth/me') {
			status = authenticated ? 200 : 401;
			payload = authenticated ? authenticatedUser : { detail: 'Not authenticated.' };
		} else if (path === '/api/mixes/feed' || path === '/api/posts/feed') {
			payload = [];
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

test('public DJ, Discover, and Community routes render through navigation', async ({ page }) => {
	const unexpectedRequests = await mockApi(page);

	await page.goto('/');
	await expect(page.getByRole('heading', { name: /Your AI DJ/ })).toBeVisible();

	await page.getByRole('link', { name: 'Discover' }).click();
	await expect(page).toHaveURL(/\/feed$/);
	await expect(page.getByRole('heading', { name: 'Discover mixes' })).toBeVisible();

	await page.getByRole('link', { name: 'Community' }).click();
	await expect(page).toHaveURL(/\/community/);
	await expect(page.getByRole('heading', { name: 'Community' })).toBeVisible();
	await expect(page.getByText('No posts here yet. Start the conversation.')).toBeVisible();
	expect(unexpectedRequests).toEqual([]);
});

test('guest users are redirected away from protected routes', async ({ page }) => {
	const unexpectedRequests = await mockApi(page);

	await page.goto('/library');
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
