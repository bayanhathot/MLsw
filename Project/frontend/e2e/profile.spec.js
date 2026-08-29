import { expect, test } from '@playwright/test';

const user = {
	id: 1,
	username: 'test-listener',
	email: 'listener@example.com',
	is_active: true
};

function musicIdentity(period = 'all', visibility = 'private') {
	const totalSeconds = period === '7d' ? 600 : period === '30d' ? 1_800 : 7_200;
	return {
		is_public: visibility === 'public',
		visibility,
		period,
		summary: {
			total_listening_seconds: totalSeconds,
			top_artist: { name: 'Nancy Ajram', seconds: totalSeconds, percentage: 100 },
			top_genre: { name: 'Arabic Pop', seconds: totalSeconds, percentage: 100 },
			top_vibe: { name: 'Upbeat', seconds: totalSeconds, percentage: 100 },
			artists_discovered: 1,
			tracks_discovered: 1,
			listening_contexts: 1,
			average_context_seconds: totalSeconds
		},
		artists: [{ name: 'Nancy Ajram', seconds: totalSeconds, percentage: 100 }],
		genres: [{ name: 'Arabic Pop', seconds: totalSeconds, percentage: 100 }],
		vibes: [{ name: 'Upbeat', seconds: totalSeconds, percentage: 100 }],
		top_tracks: [],
		time_of_day: [],
		listening_trend: [],
		recent_listening: [],
		segment_analytics: {
			most_replayed_segment: null,
			average_segment_length_seconds: null,
			time_saved_seconds: 0,
			segment_play_count: 0,
			time_saved_play_count: 0
		},
		listening_dna: {
			status: 'not_generated',
			label: null,
			summary: null,
			dimensions: [],
			version: null
		}
	};
}

/**
 * Exercise the real profile UI against a deterministic API boundary.
 * @param {import('@playwright/test').Page} page
 * @param {{ failFirstProfileLoad?: boolean }} options
 */
async function mockProfileApi(page, { failFirstProfileLoad = false } = {}) {
	let profile = {
		display_name: 'Test Listener',
		avatar_url: null,
		bio: 'Profile test fixture',
		favorite_genres: ['house'],
		theme_preference: 'dark'
	};
	let visibility = 'private';
	let profileLoads = 0;
	const calls = { profileUpdates: [], privacyUpdates: [], identityPeriods: [] };
	const unexpectedRequests = [];

	await page.routeWebSocket('**/api/ws', (socket) => socket.onMessage(() => {}));
	await page.route('**/api/**', async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		const path = url.pathname;
		const method = request.method();
		let status = 200;
		let payload;

		if (path === '/api/auth/me') {
			payload = user;
		} else if (path === '/api/users/me/profile' && method === 'GET') {
			profileLoads += 1;
			if (failFirstProfileLoad && profileLoads === 1) {
				status = 500;
				payload = { detail: 'Temporary profile failure.' };
			} else {
				payload = profile;
			}
		} else if (path === '/api/users/me/profile' && method === 'PATCH') {
			const update = request.postDataJSON();
			calls.profileUpdates.push(update);
			profile = {
				...profile,
				display_name: update.display_name,
				avatar_url: update.avatar_url,
				bio: update.bio,
				favorite_genres: update.favorite_genres
			};
			payload = profile;
		} else if (path === '/api/users/me/music-identity/privacy' && method === 'PATCH') {
			const update = request.postDataJSON();
			visibility = update.visibility;
			calls.privacyUpdates.push(update);
			// This mirrors the backend contract: privacy updates return all-time
			// analytics, even when the page is currently showing another period.
			payload = musicIdentity('all', visibility);
		} else if (path === '/api/users/me/music-identity' && method === 'GET') {
			const period = url.searchParams.get('period') || 'all';
			calls.identityPeriods.push(period);
			payload = musicIdentity(period, visibility);
		} else if (path === `/api/users/${user.username}/profile`) {
			payload = {
				id: user.id,
				username: user.username,
				display_name: profile.display_name,
				avatar_url: profile.avatar_url,
				bio: profile.bio,
				favorite_genres: profile.favorite_genres,
				member_since: '2026-08-01T00:00:00Z',
				stats: { received_upvotes: 7, received_downvotes: 1, post_count: 3, comment_count: 5 },
				music_identity_public: visibility === 'public',
				music_identity_visibility: visibility,
				friend_count: 2,
				mutual_friend_count: 0,
				published_mix_count: 1,
				relationship_status: 'self',
				viewer_has_blocked: false
			};
		} else if (path === '/api/users/me/prompt-shortcuts') {
			payload = [];
		} else if (path === '/api/notifications' || path === '/api/conversations') {
			payload = [];
		} else if (path === '/api/debug/pipeline') {
			status = 404;
			payload = { detail: 'Not found.' };
		} else {
			unexpectedRequests.push(`${method} ${path}`);
			status = 501;
			payload = { detail: `No profile-test fixture for ${path}` };
		}

		await route.fulfill({
			status,
			contentType: 'application/json',
			body: JSON.stringify(payload)
		});
	});

	return { calls, unexpectedRequests, getProfileLoads: () => profileLoads };
}

test('profile loads and saves normalized public details', async ({ page }) => {
	const api = await mockProfileApi(page);

	await page.goto('/profile');
	await expect(page.getByRole('heading', { name: 'Test Listener' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Your Music Identity' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Community activity' })).toBeVisible();
	await expect(page.getByText('Remembered DJ directions')).toHaveCount(0);

	await page.getByRole('button', { name: 'Edit profile' }).click();
	await page.getByLabel('Display name').fill('Unsaved Listener');
	await page.getByRole('button', { name: 'Close' }).click();
	await page.getByRole('button', { name: 'Edit profile' }).click();
	await expect(page.getByLabel('Display name')).toHaveValue('Test Listener');
	await page.getByLabel('Display name').fill('  Updated Listener  ');
	await page.getByLabel('Bio').fill('  House and jazz fan  ');
	await page.getByLabel('Music interests').fill('House, house, Jazz');
	await page.getByRole('button', { name: 'Save profile' }).click();

	await expect(page.getByRole('heading', { name: 'Updated Listener' })).toBeVisible();
	await expect(page.getByRole('status')).toContainText('Profile saved.');
	expect(api.calls.profileUpdates).toEqual([
		{
			display_name: 'Updated Listener',
			avatar_url: null,
			bio: 'House and jazz fan',
			favorite_genres: ['house', 'jazz']
		}
	]);
	expect(api.unexpectedRequests).toEqual([]);
});

test('profile rejects more than twenty music interests before calling the API', async ({
	page
}) => {
	const api = await mockProfileApi(page);
	await page.goto('/profile');
	await page.getByRole('button', { name: 'Edit profile' }).click();
	await page
		.getByLabel('Music interests')
		.fill(Array.from({ length: 21 }, (_, index) => `genre-${index + 1}`).join(', '));
	await page.getByRole('button', { name: 'Save profile' }).click();

	await expect(page.getByRole('alert')).toHaveText('Choose at most 20 music interests.');
	expect(api.calls.profileUpdates).toEqual([]);
	expect(api.unexpectedRequests).toEqual([]);
});

test('privacy changes preserve the selected analytics period and skip redundant requests', async ({
	page
}) => {
	const api = await mockProfileApi(page);
	await page.goto('/profile');

	await page.getByRole('button', { name: '7D' }).click();
	const totalListening = page.locator('article').filter({ hasText: 'Total listening' });
	await expect(totalListening.getByText('10m', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: '7D' })).toHaveAttribute('aria-pressed', 'true');

	await page.getByRole('button', { name: 'Everyone' }).click();
	await expect(page.getByText('Public Music Identity')).toBeVisible();
	await expect(totalListening.getByText('10m', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: '7D' })).toHaveAttribute('aria-pressed', 'true');
	await expect(page.getByRole('button', { name: 'Everyone' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	expect(api.calls.identityPeriods).toEqual(['all', '7d']);
	expect(api.calls.privacyUpdates).toEqual([{ visibility: 'public' }]);

	await page.getByRole('button', { name: '7D' }).click();
	await page.getByRole('button', { name: 'Everyone' }).click();
	await page.waitForTimeout(50);
	expect(api.calls.identityPeriods).toEqual(['all', '7d']);
	expect(api.calls.privacyUpdates).toEqual([{ visibility: 'public' }]);
	expect(api.unexpectedRequests).toEqual([]);
});

test('profile can recover when the first load fails', async ({ page }) => {
	const api = await mockProfileApi(page, { failFirstProfileLoad: true });
	await page.goto('/profile');
	await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();

	await page.getByRole('button', { name: 'Retry' }).click();
	await expect(page.getByRole('heading', { name: 'Test Listener' })).toBeVisible();
	expect(api.getProfileLoads()).toBe(2);
	expect(api.unexpectedRequests).toEqual([]);
});

test('profile fits a phone viewport without horizontal overflow', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	const api = await mockProfileApi(page);
	await page.goto('/profile');
	await expect(page.getByRole('heading', { name: 'Your Music Identity' })).toBeVisible();

	const sizes = await page.evaluate(() => ({
		viewportWidth: window.innerWidth,
		documentWidth: document.documentElement.scrollWidth
	}));
	expect(sizes.documentWidth).toBeLessThanOrEqual(sizes.viewportWidth);
	expect(api.unexpectedRequests).toEqual([]);
});
