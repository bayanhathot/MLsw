import { expect, test } from '@playwright/test';

/**
 * The real CueMix product journey. No API or WebSocket response is mocked:
 * registration, bulk upload, queue processing, catalog analysis, Studio
 * editing/preview/render/publish, Library playback, listening-event capture,
 * and Profile analytics all cross the production frontend and real backend.
 */
const BACKEND_URL = (process.env.PLAYWRIGHT_BACKEND_URL || '').replace(/\/+$/, '');
test.skip(!BACKEND_URL, 'PLAYWRIGHT_BACKEND_URL is required for the real CueMix journey.');
test.describe.configure({ mode: 'serial', timeout: 300_000 });

const RUN_ID = `${Date.now()}${Math.floor(Math.random() * 1e6)}`;

/** A small, original PCM WAV with audible pulses; fast to analyze and render. */
function journeyWav(frequency, durationSeconds = 8, sampleRate = 8000) {
	const sampleCount = durationSeconds * sampleRate;
	const dataSize = sampleCount * 2;
	const buffer = Buffer.alloc(44 + dataSize);
	buffer.write('RIFF', 0);
	buffer.writeUInt32LE(36 + dataSize, 4);
	buffer.write('WAVE', 8);
	buffer.write('fmt ', 12);
	buffer.writeUInt32LE(16, 16);
	buffer.writeUInt16LE(1, 20);
	buffer.writeUInt16LE(1, 22);
	buffer.writeUInt32LE(sampleRate, 24);
	buffer.writeUInt32LE(sampleRate * 2, 28);
	buffer.writeUInt16LE(2, 32);
	buffer.writeUInt16LE(16, 34);
	buffer.write('data', 36);
	buffer.writeUInt32LE(dataSize, 40);
	for (let index = 0; index < sampleCount; index += 1) {
		const seconds = index / sampleRate;
		const pulsePosition = seconds % 0.5;
		const envelope = pulsePosition < 0.08 ? 1 : 0.42;
		const sample = Math.sin(seconds * Math.PI * 2 * frequency) * 10_000 * envelope;
		buffer.writeInt16LE(Math.round(sample), 44 + index * 2);
	}
	return buffer;
}

/** @param {import('@playwright/test').APIResponse} response @param {string} action */
async function expectOk(response, action) {
	expect(response.ok(), `${action}: ${response.status()} ${await response.text()}`).toBe(true);
	return response;
}

test('a user uploads songs, builds and publishes a Studio mix, plays it, and sees Profile analytics', async ({
	page
}) => {
	const username = `journey${RUN_ID}`;
	const email = `${username}@example.com`;
	const password = 'journey-browser-1';
	const frequencyOffset = Number(RUN_ID.slice(-3)) / 1000;
	const artist = `Journey Artist ${RUN_ID}`;
	const album = `Journey Album ${RUN_ID}`;
	const firstTitle = `Journey Pulse ${RUN_ID}`;
	const secondTitle = `Journey Glow ${RUN_ID}`;
	const firstSegment = `Pulse opening ${RUN_ID}`;
	const secondSegment = `Glow ending ${RUN_ID}`;
	const mixTitle = `Complete Journey Mix ${RUN_ID}`;

	await page.goto('/register');
	await page.getByLabel('Username').fill(username);
	await page.getByLabel('Email').fill(email);
	await page.getByLabel('Password', { exact: true }).fill(password);
	await page.getByLabel('Confirm password').fill(password);
	await page.getByRole('button', { name: 'Create account' }).click();
	await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();

	// Record the real baseline before playback changes Music Identity.
	await page.goto('/profile');
	await expect(page.getByRole('heading', { name: username })).toBeVisible();
	await expect(page.getByTestId('profile-tracks-heard')).toHaveText('0');
	await expect(page.getByTestId('profile-listening-sessions')).toHaveText('0');

	await page.goto('/upload');
	await expect(page.getByRole('heading', { name: 'Upload music' })).toBeVisible();
	await page.getByRole('button', { name: '+ Add more sound file' }).click();
	const cards = page.locator('article.song-card');
	await expect(cards).toHaveCount(2);

	const uploads = [
		{ title: firstTitle, frequency: 330 + frequencyOffset },
		{ title: secondTitle, frequency: 494 + frequencyOffset }
	];
	for (const [index, upload] of uploads.entries()) {
		await page
			.getByLabel('Audio file')
			.nth(index)
			.setInputFiles({
				name: `journey-${index + 1}.wav`,
				mimeType: 'audio/wav',
				buffer: journeyWav(upload.frequency)
			});
		await page.getByLabel('Title', { exact: true }).nth(index).fill(upload.title);
		await page.getByLabel('Artist', { exact: true }).nth(index).fill(artist);
		await page.getByLabel('Album', { exact: true }).nth(index).fill(album);
		await page.getByLabel('Genre (optional)', { exact: true }).nth(index).fill('Electronic');
	}

	await page.getByRole('button', { name: 'Upload All' }).click();
	await expect(page.getByText('Batch finished', { exact: true })).toBeVisible({ timeout: 180_000 });
	await expect(page.locator('.status-pill').filter({ hasText: 'Uploaded' })).toHaveCount(2);
	await expect(page.getByRole('button', { name: 'Upload more songs' })).toBeVisible();

	// Library is the persistent mix library. Uploaded songs are deliberately
	// exposed as catalog sources in Studio, where both real uploads must appear.
	await page.goto('/studio');
	await expect(page.getByRole('heading', { name: 'CueMix Studio' })).toBeVisible();
	await page.getByLabel('Music source').selectOption('catalog');
	await page.getByLabel('Track search').fill(artist);
	await page.getByRole('button', { name: 'Search' }).click();
	await expect(page.getByRole('button', { name: new RegExp(firstTitle) })).toBeVisible();
	await expect(page.getByRole('button', { name: new RegExp(secondTitle) })).toBeVisible();

	async function saveTrackSegment(title, label) {
		await page.getByRole('button', { name: new RegExp(title) }).click();
		await expect(page.locator('.editor-panel').getByRole('heading', { name: title })).toBeVisible();
		await page.getByTestId('segment-start-input').fill('0');
		await page.getByTestId('segment-end-input').fill('3');
		await page.getByLabel('Segment label').fill(label);
		const editorAudio = page.locator('.editor-panel audio');
		// WaveformSegmentEditor hands WaveSurfer the live <audio> element plus the
		// catalog URL; WaveSurfer always fetches the full track itself to decode
		// waveform peaks and then swaps the element's src to the local blob: URL
		// it decoded from (see wavesurfer.js's Player#setSrc). "ready" is the
		// reliable signal that this swap has already happened, so wait for it
		// before asserting on src instead of racing the fetch.
		await expect(page.getByTestId('studio-waveform')).toHaveAttribute('data-status', 'ready', {
			timeout: 30_000
		});
		await expect(editorAudio).toHaveAttribute('src', /^blob:/);
		await page.getByRole('button', { name: 'Play segment' }).click();
		await expect
			.poll(() => editorAudio.evaluate((audio) => !audio.paused), { timeout: 10_000 })
			.toBe(true);
		const saveResponse = page.waitForResponse(
			(response) =>
				response.url().endsWith('/studio/segments') && response.request().method() === 'POST'
		);
		await page.getByRole('button', { name: 'Save segment' }).click();
		await expectOk(await saveResponse, `save ${title} segment`);
		await expect(page.locator('.banner.success')).toContainText(
			'Segment saved to your personal library.'
		);
		await expect(page.locator('input.label-input').first()).toHaveValue(label, {
			timeout: 30_000
		});
	}

	await saveTrackSegment(firstTitle, firstSegment);
	await saveTrackSegment(secondTitle, secondSegment);

	await page.getByRole('button', { name: '+ New draft' }).click();
	await page.getByLabel('New mix title').fill(mixTitle);
	await page.getByRole('button', { name: 'Create blank draft' }).click();
	await expect(
		page.getByText('Draft created. Every timeline change is saved immediately.')
	).toBeVisible();

	for (const title of [firstTitle, secondTitle]) {
		await page
			.locator('article')
			.filter({ hasText: title })
			.getByRole('button', { name: 'Add' })
			.click();
		await expect(page.locator('article.timeline-item').filter({ hasText: title })).toBeVisible();
	}
	await expect(page.locator('article.timeline-item')).toHaveCount(2);

	const transitionCard = page.locator('.transition-card');
	const transitionUpdate = page.waitForResponse(
		(response) =>
			response.url().includes('/transition') &&
			!response.url().endsWith('/transition-preview') &&
			response.request().method() === 'PATCH'
	);
	await transitionCard.locator('select').selectOption('cut');
	await expectOk(await transitionUpdate, 'change transition to cut');

	const previewResponse = page.waitForResponse(
		(response) =>
			response.url().endsWith('/transition-preview') && response.request().method() === 'POST'
	);
	await transitionCard.getByRole('button', { name: 'Preview' }).click();
	await expectOk(await previewResponse, 'preview Studio transition');
	await expect(page.locator('.editor-panel audio')).toHaveAttribute('src', /\/media\/renders\//);

	const renderResponse = page.waitForResponse(
		(response) => response.url().endsWith('/render') && response.request().method() === 'POST'
	);
	await page.getByRole('button', { name: 'Render current revision' }).click();
	await expectOk(await renderResponse, 'enqueue Studio render');
	await expect(page.locator('.banner.success')).toContainText('Current draft revision rendered.', {
		timeout: 120_000
	});
	await expect(page.getByRole('button', { name: 'Publish immutable render' })).toBeEnabled();

	const publishResponse = page.waitForResponse(
		(response) => response.url().endsWith('/publish') && response.request().method() === 'POST'
	);
	await page.getByRole('button', { name: 'Publish immutable render' }).click();
	await expectOk(await publishResponse, 'publish immutable Studio render');
	await expect(page.locator('.banner.success')).toContainText(
		'Immutable rendered version published.'
	);
	await expect(page.getByRole('button', { name: 'Duplicate into editable draft' })).toBeVisible();

	await page.goto('/library');
	await expect(page.getByRole('heading', { name: 'Mix library' })).toBeVisible();
	const mixCard = page.locator('article').filter({ hasText: mixTitle });
	await expect(mixCard).toBeVisible();
	await expect(mixCard.getByText('published', { exact: true })).toBeVisible();
	const listeningResponse = page.waitForResponse(
		(response) =>
			response.url().endsWith('/listening-events') && response.request().method() === 'POST',
		{ timeout: 30_000 }
	);
	await mixCard.getByRole('button', { name: 'Play' }).click();

	const player = page.getByRole('complementary', { name: 'Mix player' });
	await expect(player).toBeVisible();
	const autoStarted = await player
		.getByRole('button', { name: 'Pause mix' })
		.waitFor({ state: 'visible', timeout: 5_000 })
		.then(() => true)
		.catch(() => false);
	if (!autoStarted) await player.getByRole('button', { name: 'Play mix' }).click();
	await expect(player.getByRole('button', { name: 'Pause mix' })).toBeVisible();
	await expect(player.getByLabel('Playback progress').locator('span').first()).toHaveText('0:02', {
		timeout: 10_000
	});
	await player.getByRole('button', { name: 'Close mix player' }).click();
	await expectOk(await listeningResponse, 'record real mix listening');

	await page.goto('/profile');
	await expect(page.getByRole('heading', { name: username })).toBeVisible();
	await expect(page.getByTestId('profile-tracks-heard')).toHaveText('1');
	await expect(page.getByTestId('profile-listening-sessions')).toHaveText('1');
	await expect(page.getByTestId('profile-recent-listening-count')).toHaveText('1 recent');
	await expect(page.getByTestId('profile-top-artist').locator('strong')).toHaveText(artist);
	await expect(page.getByTestId('profile-total-listening').locator('strong')).not.toHaveText('0s');
});
