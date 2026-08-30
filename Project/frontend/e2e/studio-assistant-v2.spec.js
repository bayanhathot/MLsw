import { expect, test } from '@playwright/test';

const authenticatedUser = {
	id: 1,
	username: 'assistant-v2-listener',
	email: 'assistant-v2@example.com',
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

const FIXTURE_TRACK = {
	source_type: 'catalog',
	source_track_id: '101',
	title: 'Assistant V2 Fixture',
	artist: 'CueMix Tests',
	duration_ms: 10000,
	audio_url: '/api/catalog/tracks/101/audio',
	analysis_status: 'completed',
	suggested_start_ms: 1000,
	suggested_end_ms: 4000,
	phrase_boundaries_ms: [0, 2000, 6000],
	min_segment_ms: 1000,
	max_segment_ms: 8000
};

const SAVED_SEGMENT = {
	id: 7,
	user_id: 1,
	source_type: 'catalog',
	source_track_id: '101',
	title: 'Assistant V2 Fixture',
	artist: 'CueMix Tests',
	source_audio_url: '/api/catalog/tracks/101/audio',
	track_duration_ms: 10000,
	start_ms: 1000,
	end_ms: 4000,
	label: 'Saved fixture',
	created_from: 'manual',
	created_at: '2026-08-30T00:00:00Z',
	updated_at: '2026-08-30T00:00:00Z'
};

/** A minimal in-memory mix, mutated by the mocked create/add-item routes so
 * the "render button disabled with a pending plan" scenario can exercise a
 * real mix-with-segments state without a live backend. */
function makeMixState() {
	return {
		id: 501,
		session_id: 'studio_v2_fixture',
		title: 'Assistant V2 mix',
		prompt: 'Manual CueMix Studio draft',
		mode: null,
		description: null,
		cover_url: null,
		status: 'draft',
		created_at: '2026-08-30T00:00:00Z',
		published_at: null,
		is_studio: true,
		revision: 1,
		rendered_revision: null,
		published_revision: null,
		render_status: 'not_rendered',
		rendered_audio_url: null,
		published_audio_url: null,
		publication_mode: null,
		visibility: 'private',
		segments: []
	};
}

function segmentFromSaved(saved, position) {
	return {
		id: 900 + position,
		position,
		title: saved.title,
		artist: saved.artist,
		audio_url: saved.source_audio_url,
		cover_url: null,
		start_second: 0,
		end_second: 3,
		transition_to_next: 'end',
		source: saved.source_type,
		source_track_id: saved.source_track_id,
		track_duration_seconds: 10,
		genre: null,
		vibe: null,
		saved_segment_id: saved.id,
		source_audio_url: saved.source_audio_url,
		source_start_ms: saved.start_ms,
		source_end_ms: saved.end_ms,
		bpm: null,
		musical_key: null,
		key_mode: null,
		camelot: null,
		transition_type: 'cut',
		transition_duration_ms: 0,
		compatibility_score: null,
		compatibility_factors_json: null
	};
}

/**
 * @param {import('@playwright/test').Page} page
 * @param {{ chatResponse?: object }} [options]
 */
async function mockStudio(page, { chatResponse } = {}) {
	const mix = makeMixState();
	await page.routeWebSocket('**/api/ws', () => {});
	await page.route('**/api/**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		const method = request.method();

		if (path === '/api/catalog/tracks/101/audio') {
			await route.fulfill({ status: 200, contentType: 'audio/wav', body: sineWaveWav() });
			return;
		}

		let status = 200;
		let payload;

		if (path === '/api/auth/me') payload = authenticatedUser;
		else if (path === '/api/notifications' || path === '/api/conversations') payload = [];
		else if (path === '/api/debug/pipeline') {
			status = 404;
			payload = { detail: 'Not found.' };
		} else if (path === '/api/studio/segments' && method === 'GET') {
			payload = [SAVED_SEGMENT];
		} else if (path === '/api/studio/segments' && method === 'POST') {
			status = 201;
			payload = SAVED_SEGMENT;
		} else if (path === '/api/studio/tracks/search') {
			payload = [FIXTURE_TRACK];
		} else if (path === '/api/studio/mixes' && method === 'GET') {
			payload = mix.segments.length || mix.revision > 1 ? [mix] : [];
		} else if (path === '/api/studio/mixes' && method === 'POST') {
			payload = mix;
		} else if (path === `/api/studio/mixes/${mix.id}` && method === 'GET') {
			payload = mix;
		} else if (path === `/api/studio/mixes/${mix.id}/items` && method === 'POST') {
			mix.segments.push(segmentFromSaved(SAVED_SEGMENT, mix.segments.length + 1));
			mix.revision += 1;
			payload = mix;
		} else if (path === '/api/studio/assistant/chat' && method === 'POST') {
			payload = chatResponse || { available: false };
		} else if (path === '/api/studio/assistant/apply' && method === 'POST') {
			const body = request.postDataJSON();
			if (body?.add_item) {
				mix.segments.push(segmentFromSaved(SAVED_SEGMENT, mix.segments.length + 1));
			}
			mix.revision += 1;
			payload = { mix, saved_segment: null };
		} else {
			status = 501;
			payload = { detail: `No fixture for ${method} ${path}` };
		}
		await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) });
	});
}

function baseRecommendation(overrides = {}) {
	return {
		recommendation_type: 'explanation',
		base_revision: null,
		remembered_constraints: [],
		proposed_order: null,
		transition_changes: [],
		segment_bound_change: null,
		removed_item_ids: [],
		add_item: null,
		discovery_results: [],
		suggested_action: null,
		action_target_item_id: null,
		calculations: null,
		warnings: [],
		reason_tags: [],
		explanation: 'Here is what I found.',
		confidence: 0.8,
		requires_user_confirmation: true,
		...overrides
	};
}

async function createDraftMix(page) {
	await page.getByRole('button', { name: '+ New draft', exact: true }).click();
	await page.getByLabel('New mix title').fill('Assistant V2 mix');
	await page.getByRole('button', { name: 'Create blank draft', exact: true }).click();
	await expect(
		page.getByText('Draft created. Every timeline change is saved immediately.')
	).toBeVisible();
}

test('a refusal renders as a plain redirect message with no action buttons', async ({ page }) => {
	await mockStudio(page, {
		chatResponse: {
			available: true,
			recommendation: baseRecommendation({
				recommendation_type: 'refusal',
				explanation: 'I can only help with this mix, music discovery, and Studio controls.',
				reason_tags: ['out-of-scope']
			})
		}
	});
	await page.goto('/studio');
	await page
		.getByRole('button', { name: /Assistant V2 Fixture/ })
		.first()
		.click();

	await page.getByPlaceholder(/Keep the first track/).fill('Write me a poem about clouds');
	await page.getByRole('button', { name: 'Ask assistant' }).click();

	await expect(page.getByText('Outside what I can help with')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Confirm and apply plan' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Add to mix' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: /Render mix|Preview that/ })).toHaveCount(0);
});

test('discovery results can be added to the active mix', async ({ page }) => {
	await mockStudio(page, {
		chatResponse: {
			available: true,
			recommendation: baseRecommendation({
				discovery_results: [
					{
						source_type: 'catalog',
						source_track_id: '101',
						title: 'Assistant V2 Fixture',
						artist: 'CueMix Tests',
						duration_ms: 10000,
						reason: 'matches your request'
					}
				],
				explanation: 'Here is a track that matches.'
			})
		}
	});
	await page.goto('/studio');
	await createDraftMix(page);

	await page
		.getByRole('button', { name: /Assistant V2 Fixture/ })
		.first()
		.click();
	await page.getByLabel('Also search for real tracks matching this message').check();
	await page.getByPlaceholder(/Keep the first track/).fill('find something groovy');
	await page.getByRole('button', { name: 'Ask assistant' }).click();

	await expect(page.getByText('Found tracks')).toBeVisible();
	await expect(page.getByText('matches your request')).toBeVisible();
	await page.getByRole('button', { name: 'Add to mix' }).click();
	await expect(page.getByText(/Added ".*" to the mix\./)).toBeVisible();
});

test('the render button stays disabled while an unapplied plan has warnings', async ({ page }) => {
	await mockStudio(page, {
		chatResponse: {
			available: true,
			recommendation: baseRecommendation({
				recommendation_type: 'plan',
				base_revision: 2,
				proposed_order: [901],
				explanation: 'One reorder step.',
				warnings: ['One track has no key analysis']
			})
		}
	});
	await page.goto('/studio');
	await createDraftMix(page);
	await page
		.getByRole('button', { name: /Assistant V2 Fixture/ })
		.first()
		.click();
	await page.getByTestId('segment-start-input').fill('0');
	await page.getByTestId('segment-end-input').fill('3');
	await page.getByRole('button', { name: 'Save segment' }).click();
	await expect(
		page.locator('article.saved-row').filter({ hasText: 'Assistant V2 Fixture' })
	).toBeVisible();
	await page
		.locator('article.saved-row')
		.filter({ hasText: 'Assistant V2 Fixture' })
		.getByRole('button', { name: 'Add', exact: true })
		.click();

	await expect(page.getByRole('button', { name: 'Render current revision' })).toBeEnabled();

	await page.getByPlaceholder(/Keep the first track/).fill('what should come next?');
	await page.getByRole('button', { name: 'Ask assistant' }).click();
	await expect(
		page.getByText("Resolve or apply the assistant's pending suggestion first")
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Render current revision' })).toBeDisabled();
});
