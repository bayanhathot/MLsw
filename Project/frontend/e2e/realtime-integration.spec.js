import { expect, test } from '@playwright/test';

/**
 * Real-time delivery, end to end, against a REAL backend -- no mocked
 * `page.route`/`page.routeWebSocket` boundary anywhere in this file (see
 * smoke.spec.js's own WS test for the mocked counterpart this
 * corroborates: it proves the Svelte code applies an incoming WS frame
 * correctly, but pushes that frame through Playwright's own mock, so it
 * could never have caught the real production incident this test exists
 * to guard against -- redis was never a real dependency of the backend
 * container, so it silently stopped delivering every one of these four
 * surfaces while the app otherwise looked perfectly healthy).
 *
 * Requires PLAYWRIGHT_BACKEND_URL (a real backend, reachable from this
 * test runner, talking to a real Postgres AND a real Redis -- see
 * .github/workflows/cuemix-ci-cd.yml's realtime-e2e job). Skips entirely
 * when unset, so this file is inert in the existing mocked-API Playwright
 * run (frontend-checks) and only does anything in its own dedicated job.
 *
 * Two genuinely separate browser *contexts* (not just two pages/tabs in
 * one context) -- separate cookie jars, so each is authenticated as its
 * own real user, the same isolation two different people's browsers
 * would have.
 *
 * Every "acting" mutation (create a post, comment, send a DM, upload an
 * attachment) goes through a real authenticated HTTP call
 * (context.request, which shares that context's cookie jar with its
 * pages) rather than driving the composer UI -- this file's job is
 * proving genuine backend -> Redis -> WebSocket -> Svelte delivery, not
 * re-testing authoring UX smoke.spec.js and the backend's own test suite
 * already cover. Every "observing" assertion is against the real,
 * rendered page -- no reload, a bounded wait, exactly what would have
 * failed throughout the real incident.
 */

const BACKEND_URL = (process.env.PLAYWRIGHT_BACKEND_URL || '').replace(/\/+$/, '');
test.skip(!BACKEND_URL, 'PLAYWRIGHT_BACKEND_URL not set -- see this file\'s own module docstring.');

const DELIVERY_TIMEOUT_MS = 8_000;
const RUN_ID = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;

/** @param {import('@playwright/test').APIRequestContext} request */
async function registerAndLogin(request, username) {
	const email = `${username}@example.com`;
	const password = 'a-real-password-1';
	const register = await request.post(`${BACKEND_URL}/auth/register`, {
		data: { username, email, password }
	});
	expect(register.ok(), `register ${username}: ${register.status()} ${await register.text()}`).toBe(
		true
	);
	const login = await request.post(`${BACKEND_URL}/auth/login`, { data: { email, password } });
	expect(login.ok(), `login ${username}: ${login.status()} ${await login.text()}`).toBe(true);
	const user = await register.json();
	return user;
}

/**
 * @param {import('@playwright/test').APIRequestContext} fromRequest
 * @param {import('@playwright/test').APIRequestContext} toRequest
 * @param {string} fromUsername
 * @param {string} toUsername
 */
async function becomeFriends(fromRequest, toRequest, fromUsername, toUsername) {
	const sent = await fromRequest.post(`${BACKEND_URL}/friends/requests/${toUsername}`);
	expect(sent.ok(), `send friend request: ${sent.status()} ${await sent.text()}`).toBe(true);
	const { id: requestId } = await sent.json();
	const accepted = await toRequest.post(`${BACKEND_URL}/friends/requests/${requestId}/accept`);
	expect(accepted.ok(), `accept friend request: ${accepted.status()} ${await accepted.text()}`).toBe(
		true
	);
}

/**
 * Sets up two real, separately-authenticated browser contexts. Returns
 * everything a sub-test needs: each context's own page (for real UI
 * observation) and its own `request` (for real authenticated API calls
 * that drive state -- see this file's own module docstring).
 * @param {import('@playwright/test').Browser} browser
 */
async function twoAuthenticatedUsers(browser) {
	const suffix = `${RUN_ID}-${Math.floor(Math.random() * 1e6)}`;
	const usernameA = `rtA${suffix}`;
	const usernameB = `rtB${suffix}`;

	const contextA = await browser.newContext({ baseURL: BACKEND_URL });
	const contextB = await browser.newContext({ baseURL: BACKEND_URL });
	const userA = await registerAndLogin(contextA.request, usernameA);
	const userB = await registerAndLogin(contextB.request, usernameB);

	// Frontend pages navigate against PLAYWRIGHT_BASE_URL (the real
	// frontend preview, built with PUBLIC_API_BASE_URL pointed at
	// BACKEND_URL -- see the realtime-e2e CI job) -- separate contexts for
	// the frontend origin itself, sharing cookies with the API contexts
	// above via storageState, since the cookie's Domain is the backend
	// host, not the frontend's.
	const stateA = await contextA.storageState();
	const stateB = await contextB.storageState();
	const frontendContextA = await browser.newContext({ storageState: stateA });
	const frontendContextB = await browser.newContext({ storageState: stateB });

	return {
		userA,
		userB,
		usernameA,
		usernameB,
		requestA: contextA.request,
		requestB: contextB.request,
		pageA: await frontendContextA.newPage(),
		pageB: await frontendContextB.newPage(),
		cleanup: async () => {
			await Promise.all([
				contextA.close(),
				contextB.close(),
				frontendContextA.close(),
				frontendContextB.close()
			]);
		}
	};
}

test('live feed: browser A posts, browser B sees it appear with no reload', async ({ browser }) => {
	const { requestA, pageB, cleanup } = await twoAuthenticatedUsers(browser);
	try {
		await pageB.goto('/community');
		await expect(pageB.getByRole('heading', { name: 'Community' })).toBeVisible();

		const title = `Live feed test ${RUN_ID}`;
		const created = await requestA.post(`${BACKEND_URL}/posts`, {
			data: { title, body: 'Delivered over the wire, no reload needed.', kind: 'status' }
		});
		expect(created.ok(), `create post: ${created.status()} ${await created.text()}`).toBe(true);

		await expect(pageB.getByText(title)).toBeVisible({ timeout: DELIVERY_TIMEOUT_MS });
	} finally {
		await cleanup();
	}
});

test('notifications: browser A comments on browser B\'s post, browser B gets a live notification', async ({
	browser
}) => {
	const { requestA, requestB, pageB, cleanup } = await twoAuthenticatedUsers(browser);
	try {
		const postTitle = `Notification test ${RUN_ID}`;
		const created = await requestB.post(`${BACKEND_URL}/posts`, {
			data: { title: postTitle, body: 'Waiting for a comment.', kind: 'status' }
		});
		expect(created.ok()).toBe(true);
		const post = await created.json();

		await pageB.goto('/');
		await expect(pageB.getByRole('button', { name: 'Notifications' })).toBeVisible();

		const commented = await requestA.post(`${BACKEND_URL}/posts/${post.id}/comments`, {
			data: { body: 'Delivered live, this should notify the post author.' }
		});
		expect(commented.ok(), `create comment: ${commented.status()} ${await commented.text()}`).toBe(
			true
		);

		// The unread badge is the live, no-poll signal -- assert on it
		// directly rather than only opening the panel, since the panel's
		// own open handler also re-fetches over REST (loadSocialIndicators),
		// which would pass even if the live WS delivery itself were broken.
		await expect(pageB.getByRole('button', { name: 'Notifications' }).locator('b')).toHaveText(
			'1',
			{ timeout: DELIVERY_TIMEOUT_MS }
		);

		await pageB.getByRole('button', { name: 'Notifications' }).click();
		await expect(pageB.getByText('commented on your post.')).toBeVisible();
	} finally {
		await cleanup();
	}
});

test('chat: browser A sends a DM, browser B receives it live', async ({ browser }) => {
	const { requestA, requestB, usernameA, usernameB, pageB, cleanup } = await twoAuthenticatedUsers(
		browser
	);
	try {
		await becomeFriends(requestA, requestB, usernameA, usernameB);

		// The per-thread "conversation:{id}" channel is only subscribed for
		// the currently-open thread (see messages/+page.svelte's own
		// comment) -- ?with= opens B's thread with A directly, working even
		// with zero prior message history (openConversation falls back to a
		// public-profile lookup for otherUserId in that case).
		await pageB.goto(`/messages?with=${encodeURIComponent(usernameA)}`);
		await expect(pageB.getByRole('heading', { name: 'Messages' })).toBeVisible();
		// Confirms the specific thread with A finished loading (and so
		// subscribeToConversation() already ran) before A sends -- otherwise
		// this races the thread's own async open against the message send,
		// and a message that arrives before subscription is just missed.
		await expect(pageB.getByPlaceholder('Write a message…')).toBeVisible();

		const messageBody = `Live DM ${RUN_ID}, delivered with no reload`;
		const sent = await requestA.post(`${BACKEND_URL}/messages`, {
			data: { recipient_username: usernameB, body: messageBody }
		});
		expect(sent.ok(), `send message: ${sent.status()} ${await sent.text()}`).toBe(true);

		await expect(pageB.getByText(messageBody)).toBeVisible({ timeout: DELIVERY_TIMEOUT_MS });
	} finally {
		await cleanup();
	}
});

test('media: browser A uploads an attachment, browser B sees it render live', async ({ browser }) => {
	const { requestA, pageB, cleanup } = await twoAuthenticatedUsers(browser);
	try {
		await pageB.goto('/community');
		await expect(pageB.getByRole('heading', { name: 'Community' })).toBeVisible();

		const filename = `rt-${RUN_ID}.png`;
		// A minimal valid 1x1 PNG -- real bytes, decodable, not a fixture
		// stub (routers/uploads.py's own signature check would reject
		// anything that isn't).
		const pngBytes = Buffer.from(
			'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
			'base64'
		);
		const uploadJob = await requestA.post(`${BACKEND_URL}/uploads/jobs`, {
			data: pngBytes,
			headers: {
				'content-type': 'image/png',
				'x-filename': encodeURIComponent(filename)
			}
		});
		expect(uploadJob.ok(), `enqueue upload: ${uploadJob.status()} ${await uploadJob.text()}`).toBe(
			true
		);
		let job = await uploadJob.json();

		// Upload processing is async (upload_queue.py's worker pool) --
		// poll the same job-status endpoint the frontend's own uploader
		// polls, bounded, rather than assuming it finished instantly.
		const jobDeadline = Date.now() + DELIVERY_TIMEOUT_MS;
		while (job.status !== 'completed' && Date.now() < jobDeadline) {
			await new Promise((resolve) => setTimeout(resolve, 250));
			const polled = await requestA.get(`${BACKEND_URL}/uploads/jobs/${job.job_id}`);
			expect(polled.ok()).toBe(true);
			job = await polled.json();
		}
		expect(job.status, `upload job never completed: ${JSON.stringify(job)}`).toBe('completed');
		expect(job.attachment).toBeTruthy();

		const title = `Media test ${RUN_ID}`;
		const created = await requestA.post(`${BACKEND_URL}/posts`, {
			data: {
				title,
				body: 'This post should render an image live.',
				kind: 'status',
				attachment_ids: [job.attachment.id]
			}
		});
		expect(created.ok(), `create post with attachment: ${created.status()} ${await created.text()}`).toBe(
			true
		);

		await expect(pageB.getByText(title)).toBeVisible({ timeout: DELIVERY_TIMEOUT_MS });
		await expect(pageB.getByAltText(filename)).toBeVisible();
	} finally {
		await cleanup();
	}
});
