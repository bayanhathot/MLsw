import { expect, test } from '@playwright/test';

/**
 * Real long-term-memory browser coverage. Nothing in this file mocks an API
 * response: registration, session creation, coaching, logout, login, and the
 * remembered follow-up session all go through the rendered Svelte UI and the
 * real FastAPI/Postgres application started by CI's real-backend E2E job.
 */
const BACKEND_URL = (process.env.PLAYWRIGHT_BACKEND_URL || '').replace(/\/+$/, '');
test.skip(!BACKEND_URL, 'PLAYWRIGHT_BACKEND_URL is required for real memory integration tests.');
test.describe.configure({ mode: 'serial', timeout: 120_000 });

const RUN_ID = `${Date.now()}${Math.floor(Math.random() * 1e6)}`;

test('coaching memory survives logout and changes a later neutral DJ session', async ({ page }) => {
	const username = `memory${RUN_ID}`;
	const email = `${username}@example.com`;
	const password = 'memory-browser-1';

	await page.goto('/register');
	await page.getByLabel('Username').fill(username);
	await page.getByLabel('Email').fill(email);
	await page.getByLabel('Password', { exact: true }).fill(password);
	await page.getByLabel('Confirm password').fill(password);
	await page.getByRole('button', { name: 'Create account' }).click();
	await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();

	await page.getByLabel('Describe the vibe you want...').fill('hard gym workout');
	const firstSessionResponse = page.waitForResponse(
		(response) =>
			response.url() === `${BACKEND_URL}/sessions/start` && response.request().method() === 'POST'
	);
	await page.getByRole('button', { name: /Start AI DJ/ }).click();
	const firstSessionHttpResponse = await firstSessionResponse;
	const firstSession = await firstSessionHttpResponse.json();
	expect(
		firstSessionHttpResponse.ok(),
		`${firstSessionHttpResponse.status()} ${JSON.stringify(firstSession)}`
	).toBe(true);

	const keepButton = page.getByRole('button', { name: 'Keep this vibe' });
	await expect(keepButton).toBeEnabled();
	const feedbackResponse = page.waitForResponse(
		(response) =>
			response.url().includes('/sessions/') &&
			response.url().endsWith('/feedback') &&
			response.request().method() === 'POST'
	);
	await keepButton.click();
	expect((await feedbackResponse).ok()).toBe(true);
	await expect(keepButton).toHaveAttribute('aria-pressed', 'true');

	const preferences = await page.request.get(`${BACKEND_URL}/users/me/preferences`);
	expect(preferences.ok(), `${preferences.status()} ${await preferences.text()}`).toBe(true);
	expect(await preferences.json()).toEqual([
		{ feedback: 'reinforce:high:neutral', score: 1, count: 1 }
	]);

	await page.getByRole('button', { name: 'Stop AI DJ' }).click();
	await expect(page.getByRole('button', { name: /Start AI DJ/ })).toBeVisible();
	await page.getByRole('button', { name: 'Sign out' }).click();
	await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible();

	await page.getByRole('link', { name: 'Sign in' }).click();
	await page.getByLabel('Email').fill(email);
	await page.getByLabel('Password').fill(password);
	await page.getByRole('button', { name: 'Sign in' }).click();
	await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
	const rememberedPreferences = await page.request.get(`${BACKEND_URL}/users/me/preferences`);
	expect(
		rememberedPreferences.ok(),
		`${rememberedPreferences.status()} ${await rememberedPreferences.text()}`
	).toBe(true);
	expect(await rememberedPreferences.json()).toEqual([
		{ feedback: 'reinforce:high:neutral', score: 1, count: 1 }
	]);

	await page.getByLabel('Describe the vibe you want...').fill('a balanced mix');
	const rememberedSessionResponse = page.waitForResponse(
		(response) =>
			response.url() === `${BACKEND_URL}/sessions/start` && response.request().method() === 'POST'
	);
	await page.getByRole('button', { name: /Start AI DJ/ }).click();
	const rememberedSessionHttpResponse = await rememberedSessionResponse;
	const rememberedSession = await rememberedSessionHttpResponse.json();
	expect(
		rememberedSessionHttpResponse.ok(),
		`${rememberedSessionHttpResponse.status()} ${JSON.stringify(rememberedSession)}`
	).toBe(true);
	expect(rememberedSession.prompt).toBe('a balanced mix');
	await expect(page.getByText('a balanced mix', { exact: true })).toBeVisible();

	// The catalog track's own marketing label is not the parsed intent. The
	// test-only debug flag exposes the real pipeline trace in this ephemeral
	// CI stack, so this assertion proves the neutral prompt was actually
	// changed by remembered coaching instead of only proving the row exists.
	const debugResponse = await page.request.get(`${BACKEND_URL}/debug/pipeline`);
	expect(debugResponse.ok(), `${debugResponse.status()} ${await debugResponse.text()}`).toBe(true);
	const debug = await debugResponse.json();
	const rememberedDebug = debug.sessions.find(
		(session) => session.session_id === rememberedSession.id
	);
	expect(rememberedDebug, JSON.stringify(debug.sessions)).toBeTruthy();
	expect(rememberedDebug.trace.vibe_understander.intent.energy).toBe('high');
	expect(rememberedDebug.trace.vibe_understander.intent.vocals).toBe('neutral');
});
