import { expect, test } from '@playwright/test';

const authenticatedUser = {
	id: 1,
	username: 'waveform-listener',
	email: 'waveform@example.com',
	is_active: true
};

function sineWaveWav(durationSeconds = 10, sampleRate = 8000) {
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
		buffer.writeInt16LE(
			Math.round(Math.sin((index / sampleRate) * Math.PI * 440) * 8000),
			44 + index * 2
		);
	}
	return buffer;
}

async function mockStudio(page, { brokenAudio = false, assistantSuggestion = false } = {}) {
	await page.routeWebSocket('**/api/ws', () => {});
	await page.route('**/api/**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		if (path === '/api/catalog/tracks/101/audio') {
			await route.fulfill({
				status: brokenAudio ? 500 : 200,
				contentType: brokenAudio ? 'application/json' : 'audio/wav',
				body: brokenAudio ? JSON.stringify({ detail: 'broken fixture' }) : sineWaveWav()
			});
			return;
		}
		let status = 200;
		let payload;
		if (path === '/api/auth/me') payload = authenticatedUser;
		else if (path === '/api/notifications' || path === '/api/conversations') payload = [];
		else if (path === '/api/debug/pipeline') {
			status = 404;
			payload = { detail: 'Not found.' };
		} else if (path === '/api/studio/segments' && request.method() === 'GET') {
			payload = assistantSuggestion
				? [
						{
							id: 7,
							user_id: 1,
							source_type: 'catalog',
							source_track_id: '101',
							title: 'Waveform Fixture',
							artist: 'CueMix Tests',
							source_audio_url: '/api/catalog/tracks/101/audio',
							track_duration_ms: 10000,
							start_ms: 1000,
							end_ms: 4000,
							label: 'My range',
							created_from: 'manual',
							created_at: '2026-08-21T00:00:00Z',
							updated_at: '2026-08-21T00:00:00Z'
						}
					]
				: [];
		} else if (path === '/api/studio/assistant/chat' && request.method() === 'POST') {
			payload = {
				available: true,
				recommendation: {
					recommendation_type: 'plan',
					base_revision: null,
					remembered_constraints: ['Find a stronger hook'],
					proposed_order: null,
					transition_changes: [],
					segment_bound_change: {
						candidate_id: 7,
						proposed_start_ms: 5000,
						proposed_end_ms: 7000
					},
					calculations: null,
					warnings: [],
					reason_tags: ['detected_hook'],
					explanation: 'Try the detected hook.',
					confidence: 0.9,
					requires_user_confirmation: true
				}
			};
		} else if (path === '/api/studio/assistant/apply' && request.method() === 'POST') {
			payload = {
				mix: null,
				saved_segment: {
					id: 7,
					user_id: 1,
					source_type: 'catalog',
					source_track_id: '101',
					title: 'Waveform Fixture',
					artist: 'CueMix Tests',
					source_audio_url: '/api/catalog/tracks/101/audio',
					track_duration_ms: 10000,
					start_ms: 5000,
					end_ms: 7000,
					label: 'My range',
					created_from: 'manual',
					created_at: '2026-08-21T00:00:00Z',
					updated_at: '2026-08-21T00:01:00Z'
				}
			};
		} else if (path === '/api/studio/mixes') payload = [];
		else if (path === '/api/studio/tracks/search') {
			payload = [
				{
					source_type: 'catalog',
					source_track_id: '101',
					title: 'Waveform Fixture',
					artist: 'CueMix Tests',
					duration_ms: 10000,
					audio_url: '/api/catalog/tracks/101/audio',
					analysis_status: 'completed',
					suggested_start_ms: 1000,
					suggested_end_ms: 4000,
					phrase_boundaries_ms: [0, 2000, 6000],
					min_segment_ms: 1000,
					max_segment_ms: 8000
				}
			];
		} else {
			status = 501;
			payload = { detail: `No fixture for ${request.method()} ${path}` };
		}
		await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) });
	});
}

test('Studio reveals blank-draft controls from the new-draft menu', async ({ page }) => {
	await mockStudio(page);
	await page.goto('/studio');

	await expect(page.getByLabel('New mix title')).toHaveCount(0);
	await page.getByRole('button', { name: '+ New draft', exact: true }).click();
	await expect(page.getByLabel('New mix title')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Create blank draft', exact: true })).toBeVisible();
});

test('Studio waveform stays synchronized with exact numeric bounds and seeking', async ({
	page
}) => {
	await mockStudio(page);
	await page.goto('/studio');
	await page.getByRole('button', { name: /Waveform Fixture/ }).click();

	const editor = page.getByTestId('studio-waveform');
	await expect(editor).toHaveAttribute('data-status', 'ready', { timeout: 15000 });
	const startInput = page.getByTestId('segment-start-input');
	const endInput = page.getByTestId('segment-end-input');
	const selection = page.getByTestId('waveform-selection');

	await startInput.fill('2.345');
	await expect(selection).toHaveAttribute('data-start-ms', '2345');

	const rightHandle = editor.locator('[part~="region-handle-right"]');
	const handleBox = await rightHandle.boundingBox();
	expect(handleBox).not.toBeNull();
	if (handleBox) {
		await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
		await page.mouse.down();
		await page.mouse.move(handleBox.x + 65, handleBox.y + handleBox.height / 2, { steps: 8 });
		await page.mouse.up();
	}
	await expect.poll(async () => Number(await endInput.inputValue())).toBeGreaterThan(4);

	const waveformWrapper = editor.locator('[part~="wrapper"]');
	const wrapperBox = await waveformWrapper.boundingBox();
	expect(wrapperBox).not.toBeNull();
	if (wrapperBox) {
		await page.mouse.click(
			wrapperBox.x + wrapperBox.width * 0.7,
			wrapperBox.y + wrapperBox.height / 2
		);
	}
	await expect(page.getByTestId('studio-current-time')).toContainText('0:07');
});

test('Studio preserves numeric editing when waveform decoding fails', async ({ page }) => {
	await mockStudio(page, { brokenAudio: true });
	await page.goto('/studio');
	await page.getByRole('button', { name: /Waveform Fixture/ }).click();

	await expect(page.getByTestId('waveform-status')).toContainText('Waveform unavailable', {
		timeout: 15000
	});
	await expect(page.getByTestId('segment-start-input')).toBeEditable();
	await expect(page.getByRole('button', { name: 'Save segment' })).toBeEnabled();
});

test('Studio shows AI bounds separately and applies them only after confirmation', async ({
	page
}) => {
	await mockStudio(page, { assistantSuggestion: true });
	await page.goto('/studio');
	await page
		.getByRole('button', { name: /Waveform Fixture/ })
		.first()
		.click();
	await expect(page.getByTestId('studio-waveform')).toHaveAttribute('data-status', 'ready', {
		timeout: 15000
	});

	await page.getByPlaceholder(/Keep the first track/).fill('Find a stronger hook');
	await page.getByRole('button', { name: 'Ask assistant' }).click();
	await expect(page.getByRole('button', { name: 'Play AI', exact: true })).toBeVisible();
	await expect(page.getByTestId('studio-waveform').locator('[part~="ai-marker"]')).toBeVisible();
	await expect(page.getByTestId('waveform-selection')).toHaveAttribute('data-start-ms', '1000');
	await expect(page.getByTestId('waveform-selection')).toHaveAttribute('data-end-ms', '4000');
	await page.getByRole('button', { name: 'Compare', exact: true }).click();
	await expect(page.getByTestId('waveform-selection')).toHaveAttribute('data-start-ms', '1000');
	await page.getByRole('button', { name: 'Keep Mine', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Play AI', exact: true })).toHaveCount(0);

	await page.getByPlaceholder(/Keep the first track/).fill('Show the hook again');
	await page.getByRole('button', { name: 'Ask assistant' }).click();
	await expect(page.getByRole('button', { name: 'Confirm and apply plan' })).toBeVisible();

	await page.getByRole('button', { name: 'Confirm and apply plan' }).click();
	await expect(page.getByTestId('waveform-selection')).toHaveAttribute('data-start-ms', '5000');
	await expect(page.getByTestId('waveform-selection')).toHaveAttribute('data-end-ms', '7000');
});
