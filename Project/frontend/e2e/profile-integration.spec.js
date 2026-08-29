import { expect, test } from '@playwright/test';

/**
 * Real Profile statistics integration coverage. Nothing in this file mocks
 * HTTP or WebSocket traffic: actions reach the real FastAPI application and
 * every result is asserted on the rendered Svelte Profile page.
 *
 * The suite is enabled by PLAYWRIGHT_BACKEND_URL. CI supplies a production
 * frontend build pointed at that backend; local Docker runs can additionally
 * set PLAYWRIGHT_BASE_URL=http://127.0.0.1:8080.
 */
const BACKEND_URL = (process.env.PLAYWRIGHT_BACKEND_URL || '').replace(/\/+$/, '');
const FRONTEND_URL = (process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:4173').replace(
	/\/+$/,
	''
);
test.skip(!BACKEND_URL, 'PLAYWRIGHT_BACKEND_URL is required for real Profile integration tests.');
// Production intentionally runs one backend process while its upload workers
// provide the safe parallelism. Keep these stateful, render-heavy scenarios
// serial so a real mix render cannot starve unrelated Profile assertions.
test.describe.configure({ mode: 'serial', timeout: 120_000 });

const RUN_ID = `${Date.now()}${Math.floor(Math.random() * 1e6)}`;

/** @param {import('@playwright/test').APIResponse} response @param {string} action */
async function expectOk(response, action) {
	expect(response.ok(), `${action}: ${response.status()} ${await response.text()}`).toBe(true);
	return response.json().catch(() => null);
}

/** @param {import('@playwright/test').Browser} browser @param {string} label */
async function createUser(browser, label) {
	const username = `pf${label}${RUN_ID}${Math.floor(Math.random() * 1e4)}`;
	const email = `${username}@example.com`;
	const password = 'profile-statistics-1';
	const context = await browser.newContext({ baseURL: FRONTEND_URL });
	await expectOk(
		await context.request.post(`${BACKEND_URL}/auth/register`, {
			data: { username, email, password }
		}),
		`register ${username}`
	);
	await expectOk(
		await context.request.post(`${BACKEND_URL}/auth/login`, { data: { email, password } }),
		`login ${username}`
	);
	return { username, context, request: context.request, page: await context.newPage() };
}

/** @param {{ username: string, page: import('@playwright/test').Page }} user */
async function openOwnProfile(user) {
	await user.page.goto('/profile');
	await expect(user.page.getByRole('heading', { name: user.username })).toBeVisible();
}

/** @param {{ username: string, page: import('@playwright/test').Page }} user */
async function refreshOwnProfile(user) {
	await user.page.reload();
	await expect(user.page.getByRole('heading', { name: user.username })).toBeVisible();
}

/** @param {import('@playwright/test').Page} page @param {string} testId @param {number} value */
async function expectCounter(page, testId, value) {
	await expect(page.getByTestId(testId)).toHaveText(String(value));
}

/** @param {import('@playwright/test').APIRequestContext} request @param {string} body @param {string} [visibility] @param {boolean} [anonymous] */
async function createPost(request, body, visibility = 'public', anonymous = false) {
	return expectOk(
		await request.post(`${BACKEND_URL}/posts`, {
			data: {
				title: `Profile integration: ${body}`,
				body,
				kind: anonymous ? 'discussion' : 'status',
				visibility,
				is_anonymous: anonymous
			}
		}),
		'create Community post'
	);
}

/** @param {import('@playwright/test').APIRequestContext} request @param {number} postId @param {string} body */
async function createComment(request, postId, body) {
	return expectOk(
		await request.post(`${BACKEND_URL}/posts/${postId}/comments`, { data: { body } }),
		'create Community comment'
	);
}

/** @param {import('@playwright/test').APIRequestContext} request @param {string} prompt */
async function createPublishedMix(request, prompt) {
	const mix = await expectOk(
		await request.post(`${BACKEND_URL}/mixes/start`, { data: { prompt } }),
		'create mix draft'
	);
	await expectOk(await request.post(`${BACKEND_URL}/mixes/${mix.id}/publish`), 'publish mix');
	return mix;
}

/** @param {{ request: import('@playwright/test').APIRequestContext, username: string }} sender @param {{ request: import('@playwright/test').APIRequestContext, username: string }} receiver */
async function becomeFriends(sender, receiver) {
	const sent = await expectOk(
		await sender.request.post(`${BACKEND_URL}/friends/requests/${receiver.username}`),
		'send friend request'
	);
	await expectOk(
		await receiver.request.post(`${BACKEND_URL}/friends/requests/${sent.id}/accept`),
		'accept friend request'
	);
}

/** @param {number} seconds */
function duration(seconds) {
	const safe = Math.max(0, Number(seconds || 0));
	const hours = Math.floor(safe / 3600);
	const minutes = Math.floor((safe % 3600) / 60);
	if (hours) return `${hours.toLocaleString()}h ${minutes}m`;
	if (minutes) return `${minutes}m`;
	return `${Math.floor(safe)}s`;
}

/** @param {Record<string, any>[]} events @param {string} field */
function topMetricName(events, field) {
	const grouped = new Map();
	for (const event of events) {
		const name = typeof event[field] === 'string' ? event[field].trim() : '';
		if (!name) continue;
		const key = name.toLocaleLowerCase();
		const current = grouped.get(key) || { name, seconds: 0 };
		current.seconds += event.seconds_listened;
		grouped.set(key, current);
	}
	return [...grouped.values()].sort(
		(left, right) =>
			right.seconds - left.seconds || left.name.toLocaleLowerCase().localeCompare(right.name)
	)[0]?.name;
}

test('Community Profile counters follow create, vote, undo, and delete actions', async ({
	browser
}) => {
	const alice = await createUser(browser, 'communitya');
	const bob = await createUser(browser, 'communityb');
	try {
		await openOwnProfile(alice);
		await expect(alice.page.getByText('Comments received', { exact: true })).toBeVisible();
		for (const id of [
			'profile-posts-count',
			'profile-comments-count',
			'profile-upvotes-count',
			'profile-downvotes-count'
		]) {
			await expectCounter(alice.page, id, 0);
		}

		const alicePost = await createPost(alice.request, 'Alice post');
		await refreshOwnProfile(alice);
		await expectCounter(alice.page, 'profile-posts-count', 1);

		const bobPost = await createPost(bob.request, 'Bob post');
		await refreshOwnProfile(alice);
		await expectCounter(alice.page, 'profile-posts-count', 1);

		const aliceComment = await createComment(alice.request, bobPost.id, 'Alice comment');
		await refreshOwnProfile(alice);
		await expectCounter(alice.page, 'profile-comments-count', 0);

		await createComment(bob.request, alicePost.id, 'Bob comment');
		await refreshOwnProfile(alice);
		await expectCounter(alice.page, 'profile-comments-count', 1);

		await expectOk(
			await bob.request.post(`${BACKEND_URL}/posts/${alicePost.id}/vote`, {
				data: { value: 1 }
			}),
			'upvote Alice post'
		);
		await refreshOwnProfile(alice);
		await expectCounter(alice.page, 'profile-upvotes-count', 1);

		// Votes cast by Alice affect Bob's received total, not Alice's total.
		await expectOk(
			await alice.request.post(`${BACKEND_URL}/posts/${bobPost.id}/vote`, {
				data: { value: 1 }
			}),
			'Alice upvotes Bob post'
		);
		await refreshOwnProfile(alice);
		await expectCounter(alice.page, 'profile-upvotes-count', 1);

		await expectOk(
			await bob.request.post(`${BACKEND_URL}/posts/${alicePost.id}/vote`, {
				data: { value: -1 }
			}),
			'change Alice post vote to downvote'
		);
		await refreshOwnProfile(alice);
		await expectCounter(alice.page, 'profile-upvotes-count', 0);
		await expectCounter(alice.page, 'profile-downvotes-count', 1);

		await expectOk(
			await bob.request.delete(`${BACKEND_URL}/posts/${alicePost.id}/vote`),
			'undo Alice post vote'
		);
		await refreshOwnProfile(alice);
		await expectCounter(alice.page, 'profile-downvotes-count', 0);

		await expectOk(
			await bob.request.post(`${BACKEND_URL}/posts/comments/${aliceComment.id}/vote`, {
				data: { value: 1 }
			}),
			'upvote Alice comment'
		);
		await refreshOwnProfile(alice);
		// The profile dashboard tracks votes received on posts, not comments.
		await expectCounter(alice.page, 'profile-upvotes-count', 0);

		await expectOk(
			await alice.request.delete(`${BACKEND_URL}/posts/${bobPost.id}/comments/${aliceComment.id}`),
			'delete Alice comment'
		);
		await refreshOwnProfile(alice);
		await expectCounter(alice.page, 'profile-comments-count', 1);
		await expectCounter(alice.page, 'profile-upvotes-count', 0);

		await expectOk(
			await alice.request.delete(`${BACKEND_URL}/posts/${alicePost.id}`),
			'delete Alice post'
		);
		await refreshOwnProfile(alice);
		await expectCounter(alice.page, 'profile-posts-count', 0);
		await expectCounter(alice.page, 'profile-comments-count', 0);
	} finally {
		await Promise.all([alice.context.close(), bob.context.close()]);
	}
});

test('Friends counter changes only for accepted friendships and reverses on removal', async ({
	browser
}) => {
	const alice = await createUser(browser, 'frienda');
	const bob = await createUser(browser, 'friendb');
	const carol = await createUser(browser, 'friendc');
	try {
		await openOwnProfile(alice);
		await expect(alice.page.getByTestId('profile-friends-count')).toHaveText('0 friends');

		const pending = await expectOk(
			await alice.request.post(`${BACKEND_URL}/friends/requests/${bob.username}`),
			'send pending friend request'
		);
		await refreshOwnProfile(alice);
		await expect(alice.page.getByTestId('profile-friends-count')).toHaveText('0 friends');

		await expectOk(
			await bob.request.post(`${BACKEND_URL}/friends/requests/${pending.id}/accept`),
			'accept friendship'
		);
		await refreshOwnProfile(alice);
		await expect(alice.page.getByTestId('profile-friends-count')).toHaveText('1 friends');

		await becomeFriends(bob, carol);
		await refreshOwnProfile(alice);
		await expect(alice.page.getByTestId('profile-friends-count')).toHaveText('1 friends');

		await expectOk(
			await alice.request.delete(`${BACKEND_URL}/friends/${bob.username}`),
			'remove friend'
		);
		await refreshOwnProfile(alice);
		await expect(alice.page.getByTestId('profile-friends-count')).toHaveText('0 friends');
	} finally {
		await Promise.all([alice.context.close(), bob.context.close(), carol.context.close()]);
	}
});

test('real listening events update every action-driven Music Identity metric', async ({
	browser
}) => {
	test.setTimeout(120_000);
	const alice = await createUser(browser, 'music');
	try {
		await openOwnProfile(alice);
		await expect(alice.page.getByTestId('profile-total-listening').locator('strong')).toHaveText(
			'0m'
		);
		for (const id of [
			'profile-artists-heard',
			'profile-tracks-heard',
			'profile-listening-sessions'
		]) {
			await expectCounter(alice.page, id, 0);
		}

		const sessionOne = await expectOk(
			await alice.request.post(`${BACKEND_URL}/sessions/start`, {
				data: { prompt: 'high energy gym' }
			}),
			'start first DJ session'
		);
		const firstEvent = await expectOk(
			await alice.request.post(`${BACKEND_URL}/listening-events`, {
				data: {
					client_event_id: `listen:${RUN_ID}:one`,
					session_id: sessionOne.id,
					started_at: new Date().toISOString(),
					seconds_listened: 12,
					skipped: true
				}
			}),
			'record first listening event'
		);

		await refreshOwnProfile(alice);
		await expect(alice.page.getByTestId('profile-total-listening').locator('strong')).toHaveText(
			'12s'
		);
		await expectCounter(alice.page, 'profile-artists-heard', 1);
		await expectCounter(alice.page, 'profile-tracks-heard', 1);
		await expectCounter(alice.page, 'profile-listening-sessions', 1);
		await expect(alice.page.getByTestId('profile-average-session')).toHaveText('12s');
		await expect(alice.page.getByTestId('profile-top-artist').locator('strong')).toHaveText(
			firstEvent.artist_name
		);
		await expect(alice.page.getByTestId('profile-top-vibe').locator('strong')).toHaveText(
			firstEvent.vibe
		);

		const sessionTwo = await expectOk(
			await alice.request.post(`${BACKEND_URL}/sessions/start`, {
				data: { prompt: 'emotional vocals' }
			}),
			'start second DJ session'
		);
		const secondEvent = await expectOk(
			await alice.request.post(`${BACKEND_URL}/listening-events`, {
				data: {
					client_event_id: `listen:${RUN_ID}:two`,
					session_id: sessionTwo.id,
					started_at: new Date().toISOString(),
					seconds_listened: 8,
					skipped: true
				}
			}),
			'record second listening event'
		);
		const replayEvent = await expectOk(
			await alice.request.post(`${BACKEND_URL}/listening-events`, {
				data: {
					client_event_id: `listen:${RUN_ID}:replay`,
					session_id: sessionOne.id,
					started_at: new Date().toISOString(),
					seconds_listened: 6,
					skipped: true
				}
			}),
			'record a replay of the first segment'
		);

		const expectedTotal =
			firstEvent.seconds_listened + secondEvent.seconds_listened + replayEvent.seconds_listened;
		const recordedEvents = [firstEvent, secondEvent, replayEvent];
		const expectedArtists = new Set(
			recordedEvents.map((event) => event.artist_name.trim().toLocaleLowerCase())
		).size;
		const expectedTracks = new Set(
			recordedEvents.map((event) => `${event.source}:${event.source_track_id}`)
		).size;
		const expectedSaved = recordedEvents.reduce(
			(total, event) => total + Math.max(0, event.track_duration_seconds - event.seconds_listened),
			0
		);
		const expectedSegmentLength =
			recordedEvents.reduce(
				(total, event) => total + event.segment_end_second - event.segment_start_second,
				0
			) / recordedEvents.length;
		const expectedTopArtist = topMetricName(recordedEvents, 'artist_name');
		const expectedTopGenre = topMetricName(recordedEvents, 'genre');
		const expectedTopVibe = topMetricName(recordedEvents, 'vibe');

		await refreshOwnProfile(alice);
		await expect(alice.page.getByTestId('profile-total-listening').locator('strong')).toHaveText(
			duration(expectedTotal)
		);
		await expectCounter(alice.page, 'profile-artists-heard', expectedArtists);
		await expectCounter(alice.page, 'profile-tracks-heard', expectedTracks);
		await expectCounter(alice.page, 'profile-listening-sessions', 2);
		await expect(alice.page.getByTestId('profile-average-session')).toHaveText(
			duration(Math.round(expectedTotal / 2))
		);
		await expect(
			alice.page.getByTestId('profile-average-segment-length').locator('strong')
		).toHaveText(duration(expectedSegmentLength));
		await expect(alice.page.getByTestId('profile-time-saved').locator('strong')).toHaveText(
			duration(expectedSaved)
		);
		await expect(alice.page.getByTestId('profile-time-saved')).toContainText('across 3 plays');
		await expect(
			alice.page.getByTestId('profile-most-replayed-segment').locator('strong')
		).toHaveText(firstEvent.track_title);
		await expect(alice.page.getByTestId('profile-most-replayed-segment')).toContainText(
			'1 replay across 2 plays'
		);
		await expect(alice.page.getByTestId('profile-top-genre').locator('strong')).toHaveText(
			expectedTopGenre || 'Not enough data'
		);
		await expect(alice.page.getByTestId('profile-top-artist').locator('strong')).toHaveText(
			expectedTopArtist
		);
		await expect(alice.page.getByTestId('profile-top-vibe').locator('strong')).toHaveText(
			expectedTopVibe
		);

		const topTracksPanel = alice.page
			.getByRole('heading', { name: 'Top tracks' })
			.locator('xpath=ancestor::section');
		await expect(topTracksPanel).toContainText(firstEvent.track_title);
		await expect(topTracksPanel).toContainText(secondEvent.track_title);
		const artistsPanel = alice.page
			.getByRole('heading', { name: 'Your top artists' })
			.locator('xpath=ancestor::section');
		await expect(artistsPanel).toContainText(firstEvent.artist_name);
		await expect(artistsPanel).toContainText(secondEvent.artist_name);
		const genresPanel = alice.page
			.getByRole('heading', { name: 'Genre distribution' })
			.locator('xpath=ancestor::section');
		await expect(genresPanel).toContainText(expectedTopGenre || 'Your sound map is empty');
		const timeOfDayPanel = alice.page
			.getByRole('heading', { name: 'When you listen' })
			.locator('xpath=ancestor::section');
		await expect(timeOfDayPanel).toContainText('100%');
		await expect(alice.page.getByRole('heading', { name: 'Listening trend' })).toHaveCount(0);
		const vibesPanel = alice.page
			.getByRole('heading', { name: 'Your recurring vibes' })
			.locator('xpath=ancestor::section');
		await expect(vibesPanel).toContainText(firstEvent.vibe);
		await expect(vibesPanel).toContainText(secondEvent.vibe);
		await expect(alice.page.getByTestId('profile-recent-listening-count')).toHaveText('2 recent');
		const recentPanel = alice.page
			.getByRole('heading', { name: 'Listening sessions' })
			.locator('xpath=ancestor::section');
		await expect(
			recentPanel.getByText(sessionOne.vibeLabel, { exact: true }).first()
		).toBeVisible();
		await expect(
			recentPanel.getByText(sessionTwo.vibeLabel, { exact: true }).first()
		).toBeVisible();
		await expect(alice.page.getByRole('heading', { name: 'Your Listening DNA' })).toHaveCount(0);

		await expectOk(
			await alice.request.patch(`${BACKEND_URL}/users/me/music-identity/privacy`, {
				data: { visibility: 'public' }
			}),
			'publish action-driven Music Identity'
		);
		const publicContext = await browser.newContext({ baseURL: FRONTEND_URL });
		try {
			const publicPage = await publicContext.newPage();
			await publicPage.goto(`/users/${alice.username}`);
			await expect(publicPage.getByTestId('public-profile-top-artist')).toHaveText(
				expectedTopArtist,
				{ timeout: 15_000 }
			);
			await expect(publicPage.getByTestId('public-profile-top-genre')).toHaveText(
				expectedTopGenre || '—'
			);
			await expect(publicPage.getByTestId('public-profile-top-vibe')).toHaveText(expectedTopVibe);
			await expect(publicPage.getByTestId('public-profile-total-listening')).toHaveText(
				duration(expectedTotal)
			);
			await publicPage.getByRole('button', { name: 'Open Music Identity →' }).click();
			await expect(publicPage.getByTestId('profile-total-listening').locator('strong')).toHaveText(
				duration(expectedTotal)
			);
		} finally {
			await publicContext.close();
		}
	} finally {
		await alice.context.close();
	}
});

test('public Profile counters and Music Identity respect stranger, friend, and owner privacy', async ({
	browser
}) => {
	test.setTimeout(120_000);
	const alice = await createUser(browser, 'privacya');
	const bob = await createUser(browser, 'privacyb');
	const carol = await createUser(browser, 'privacyc');
	try {
		await createPost(alice.request, 'Named public activity');
		await createPost(alice.request, 'Named friends activity', 'friends');
		await createPost(alice.request, 'Anonymous public activity', 'public', true);
		await becomeFriends(alice, carol);

		await alice.page.goto('/profile');
		await expectCounter(alice.page, 'profile-posts-count', 3);

		await bob.page.goto(`/users/${alice.username}`);
		await expect(bob.page.getByText('Listening analytics are private')).toBeVisible({
			timeout: 15_000
		});
		await expectCounter(bob.page, 'public-profile-friends-summary', 1);
		await expectCounter(bob.page, 'public-profile-mixes-summary', 0);
		await expectCounter(bob.page, 'public-profile-posts-summary', 1);
		await expect(bob.page.getByTestId('public-profile-mutual-friends')).toHaveCount(0);

		const aliceMix = await createPublishedMix(alice.request, 'Profile count electronic mix');
		await bob.page.reload();
		await expectCounter(bob.page, 'public-profile-mixes-summary', 1);
		await bob.page.getByRole('button', { name: 'Mixes', exact: true }).click();
		await expect(bob.page.getByRole('heading', { name: '1 published mixes' })).toBeVisible();
		await expect(bob.page.getByText(aliceMix.title, { exact: true }).first()).toBeVisible();

		await createPublishedMix(bob.request, 'Other user profile count mix');
		await bob.page.reload();
		await expectCounter(bob.page, 'public-profile-mixes-summary', 1);

		await becomeFriends(bob, carol);
		await bob.page.reload();
		await expectCounter(bob.page, 'public-profile-friends-summary', 1);
		await expect(bob.page.getByTestId('public-profile-mutual-friends')).toHaveText(
			'1 mutual friends'
		);
		await bob.page.getByRole('button', { name: 'Activity', exact: true }).click();
		await expectCounter(bob.page, 'public-profile-posts-count', 1);
		await expectCounter(bob.page, 'public-profile-comments-count', 0);

		await carol.page.goto(`/users/${alice.username}`);
		await carol.page.getByRole('button', { name: 'Activity', exact: true }).click();
		await expectCounter(carol.page, 'public-profile-posts-count', 2);

		await expectOk(
			await alice.request.patch(`${BACKEND_URL}/users/me/music-identity/privacy`, {
				data: { visibility: 'friends' }
			}),
			'share Music Identity with friends'
		);
		await bob.page.reload();
		await expect(bob.page.getByText('Listening analytics are private')).toBeVisible({
			timeout: 15_000
		});
		await carol.page.reload();
		await expect(carol.page.getByRole('heading', { name: 'How they listen' })).toBeVisible();

		await expectOk(
			await carol.request.delete(`${BACKEND_URL}/friends/${alice.username}`),
			'remove privacy-test friendship'
		);
		await carol.page.reload();
		await expect(carol.page.getByText('Listening analytics are private')).toBeVisible({
			timeout: 15_000
		});
		await expectCounter(carol.page, 'public-profile-friends-summary', 0);
		await carol.page.getByRole('button', { name: 'Activity', exact: true }).click();
		await expectCounter(carol.page, 'public-profile-posts-count', 1);
		await bob.page.reload();
		await expectCounter(bob.page, 'public-profile-friends-summary', 0);
		await expect(bob.page.getByTestId('public-profile-mutual-friends')).toHaveCount(0);

		await expectOk(
			await alice.request.patch(`${BACKEND_URL}/users/me/music-identity/privacy`, {
				data: { visibility: 'public' }
			}),
			'publish Music Identity'
		);
		await bob.page.reload();
		await expect(bob.page.getByRole('heading', { name: 'How they listen' })).toBeVisible();

		await expectOk(
			await alice.request.patch(`${BACKEND_URL}/users/me/music-identity/privacy`, {
				data: { visibility: 'private' }
			}),
			'make Music Identity private again'
		);
		await bob.page.reload();
		await expect(bob.page.getByText('Listening analytics are private')).toBeVisible({
			timeout: 15_000
		});
	} finally {
		await Promise.all([alice.context.close(), bob.context.close(), carol.context.close()]);
	}
});
