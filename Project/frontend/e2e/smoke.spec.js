import { expect, test } from '@playwright/test';

const authenticatedUser = {
	id: 1,
	username: 'test-listener',
	email: 'listener@example.com',
	is_active: true
};

/**
 * Mock the API boundary while exercising the actual production frontend. The
 * returned list makes every unplanned request fail the assertion instead of
 * silently turning this into a visual-only smoke test.
 *
 * @param {import('@playwright/test').Page} page
 * @param {{ authenticated?: boolean }} options
 */
async function mockApi(page, { authenticated = false } = {}) {
	const unexpectedRequests = [];

	await page.routeWebSocket('**/api/ws/notifications', (socket) => {
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
			payload = { display_name: 'Test Listener', bio: 'Browser smoke fixture' };
		} else if (path === '/api/users/me/preferences') {
			payload = [];
		} else if (path === `/api/users/${authenticatedUser.username}/stats`) {
			payload = {
				received_upvotes: 0,
				received_downvotes: 0,
				post_count: 0,
				comment_count: 0
			};
		} else if (path === '/api/notifications') {
			payload = [];
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

test('public home, mix feed, and forum routes render through navigation', async ({ page }) => {
	const unexpectedRequests = await mockApi(page);

	await page.goto('/');
	await expect(page.getByRole('heading', { name: /Your AI DJ/ })).toBeVisible();

	await page.getByRole('link', { name: 'Mixes' }).click();
	await expect(page).toHaveURL(/\/feed$/);
	await expect(page.getByRole('heading', { name: 'Discover mixes' })).toBeVisible();
	await expect(page.getByText('No mixes have been published yet.')).toBeVisible();

	await page.getByRole('link', { name: 'Forum' }).click();
	await expect(page).toHaveURL(/\/forum$/);
	await expect(page.getByRole('heading', { name: 'Talk music, focus, and flow.' })).toBeVisible();
	await expect(page.getByText('No discussions yet. Be the first to start one.')).toBeVisible();
	expect(unexpectedRequests).toEqual([]);
});

test('guest users are redirected away from protected routes', async ({ page }) => {
	const unexpectedRequests = await mockApi(page);

	await page.goto('/library');
	await expect(page).toHaveURL(/\/login$/);
	await expect(page.getByRole('heading', { name: 'Sign in.' })).toBeVisible();
	expect(unexpectedRequests).toEqual([]);
});

test('authenticated library, profile, and social routes load their API state', async ({ page }) => {
	const unexpectedRequests = await mockApi(page, { authenticated: true });

	await page.goto('/library');
	await expect(page.getByRole('heading', { name: 'Mix library' })).toBeVisible();
	await expect(page.getByText('No generated drafts yet.')).toBeVisible();

	await page.getByRole('link', { name: 'Profile' }).click();
	await expect(page.getByRole('heading', { name: authenticatedUser.username })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Forum activity' })).toBeVisible();

	await page.getByRole('link', { name: 'Social' }).click();
	await expect(page.getByRole('heading', { name: 'Messages and notifications' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Direct messages' })).toBeVisible();
	expect(unexpectedRequests).toEqual([]);
});
