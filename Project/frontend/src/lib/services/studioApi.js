import { apiRequest, backendMediaUrl } from './api.js';
import { normalizeMix } from './mixApi.js';

/** @param {unknown} value @returns {import('../types.js').StudioTrack} */
export function normalizeStudioTrack(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	return {
		sourceType: raw.source_type === 'audius' ? 'audius' : 'catalog',
		sourceTrackId: String(raw.source_track_id || ''),
		title: String(raw.title || 'Unknown title'),
		artist: String(raw.artist || 'Unknown artist'),
		album: raw.album ?? null,
		genre: raw.genre ?? null,
		vibe: raw.vibe ?? null,
		durationMs: Number(raw.duration_ms || 0),
		audioUrl: backendMediaUrl(String(raw.audio_url || '')),
		coverUrl: raw.cover_url ? backendMediaUrl(String(raw.cover_url)) : null,
		analysisStatus: raw.analysis_status ?? null,
		suggestedStartMs: raw.suggested_start_ms == null ? null : Number(raw.suggested_start_ms),
		suggestedEndMs: raw.suggested_end_ms == null ? null : Number(raw.suggested_end_ms),
		phraseBoundariesMs: Array.isArray(raw.phrase_boundaries_ms)
			? raw.phrase_boundaries_ms.map(Number).filter(Number.isFinite)
			: [],
		minSegmentMs: Number(raw.min_segment_ms || 1000),
		maxSegmentMs: Number(raw.max_segment_ms || raw.duration_ms || 300000),
		bpm: raw.bpm == null ? null : Number(raw.bpm),
		musicalKey: raw.musical_key ?? null,
		camelot: raw.camelot ?? null
	};
}

/** @param {unknown} value @returns {import('../types.js').SavedSegment} */
export function normalizeSavedSegment(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	return {
		id: Number(raw.id),
		userId: Number(raw.user_id),
		sourceType: raw.source_type === 'audius' ? 'audius' : 'catalog',
		sourceTrackId: String(raw.source_track_id || ''),
		title: String(raw.title || ''),
		artist: String(raw.artist || ''),
		album: raw.album ?? null,
		genre: raw.genre ?? null,
		vibe: raw.vibe ?? null,
		sourceAudioUrl: backendMediaUrl(String(raw.source_audio_url || '')),
		coverUrl: raw.cover_url ? backendMediaUrl(String(raw.cover_url)) : null,
		trackDurationMs: Number(raw.track_duration_ms || 0),
		startMs: Number(raw.start_ms || 0),
		endMs: Number(raw.end_ms || 0),
		label: String(raw.label || 'Saved segment'),
		createdFrom: String(raw.created_from || 'manual'),
		bpm: raw.bpm == null ? null : Number(raw.bpm),
		musicalKey: raw.musical_key ?? null,
		camelot: raw.camelot ?? null,
		createdAt: String(raw.created_at || ''),
		updatedAt: String(raw.updated_at || '')
	};
}

/** @param {string} query @param {'all'|'catalog'|'audius'} [source] */
export async function searchStudioTracks(query, source = 'all') {
	const raw = await apiRequest(
		`/studio/tracks/search?q=${encodeURIComponent(query)}&source=${encodeURIComponent(source)}`
	);
	return Array.isArray(raw) ? raw.map(normalizeStudioTrack) : [];
}

/** @param {string} [query] */
export async function listSavedSegments(query = '') {
	const raw = await apiRequest(`/studio/segments?q=${encodeURIComponent(query)}`);
	return Array.isArray(raw) ? raw.map(normalizeSavedSegment) : [];
}

/** @param {{sourceType:'catalog'|'audius', sourceTrackId:string, startMs:number, endMs:number, label:string, createdFrom?:string}} input */
export async function createSavedSegment(input) {
	return normalizeSavedSegment(
		await apiRequest('/studio/segments', {
			method: 'POST',
			body: JSON.stringify({
				source_type: input.sourceType,
				source_track_id: input.sourceTrackId,
				start_ms: input.startMs,
				end_ms: input.endMs,
				label: input.label,
				created_from: input.createdFrom || 'manual'
			})
		})
	);
}

/** @param {number} segmentId @param {Record<string, unknown>} changes */
export async function updateSavedSegment(segmentId, changes) {
	return normalizeSavedSegment(
		await apiRequest(`/studio/segments/${segmentId}`, {
			method: 'PATCH',
			body: JSON.stringify(changes)
		})
	);
}

/** @param {number} segmentId */
export function deleteSavedSegment(segmentId) {
	return apiRequest(`/studio/segments/${segmentId}`, { method: 'DELETE' });
}

export async function listStudioMixes() {
	const raw = await apiRequest('/studio/mixes');
	return Array.isArray(raw) ? raw.map(normalizeMix) : [];
}

/** @param {number} mixId */
export async function getStudioMix(mixId) {
	return normalizeMix(await apiRequest(`/studio/mixes/${mixId}`));
}

/** @param {string} title @param {string|null} [description] */
export async function createStudioMix(title, description = null) {
	return normalizeMix(
		await apiRequest('/studio/mixes', {
			method: 'POST',
			body: JSON.stringify({ title, description })
		})
	);
}

/** @param {number} mixId @param {number} revision @param {Record<string, unknown>} changes */
export async function updateStudioMix(mixId, revision, changes) {
	return normalizeMix(
		await apiRequest(`/studio/mixes/${mixId}`, {
			method: 'PATCH',
			body: JSON.stringify({ expected_revision: revision, ...changes })
		})
	);
}

/** @param {number} mixId @param {number} revision @param {number} savedSegmentId */
export async function addSegmentToMix(mixId, revision, savedSegmentId) {
	return normalizeMix(
		await apiRequest(`/studio/mixes/${mixId}/items`, {
			method: 'POST',
			body: JSON.stringify({ expected_revision: revision, saved_segment_id: savedSegmentId })
		})
	);
}

/** @param {number} mixId @param {number} revision @param {number[]} segmentIds */
export async function reorderStudioMix(mixId, revision, segmentIds) {
	return normalizeMix(
		await apiRequest(`/studio/mixes/${mixId}/items/reorder`, {
			method: 'PUT',
			body: JSON.stringify({ expected_revision: revision, segment_ids: segmentIds })
		})
	);
}

/** @param {number} mixId @param {number} revision @param {number} itemId */
export async function removeMixItem(mixId, revision, itemId) {
	return normalizeMix(
		await apiRequest(`/studio/mixes/${mixId}/items/${itemId}?expected_revision=${revision}`, {
			method: 'DELETE'
		})
	);
}

/** @param {number} mixId @param {number} itemId @param {number} revision @param {'cut'|'crossfade'|'fade_in_out'} type @param {number} durationMs */
export async function updateStudioTransition(mixId, itemId, revision, type, durationMs) {
	return normalizeMix(
		await apiRequest(`/studio/mixes/${mixId}/items/${itemId}/transition`, {
			method: 'PATCH',
			body: JSON.stringify({
				expected_revision: revision,
				transition_type: type,
				duration_ms: durationMs
			})
		})
	);
}

/** @param {number} mixId @param {number} itemId */
export async function previewStudioTransition(mixId, itemId) {
	const raw = await apiRequest(`/studio/mixes/${mixId}/items/${itemId}/transition-preview`, {
		method: 'POST',
		timeoutMs: 45_000
	});
	return backendMediaUrl(String(raw?.audio_url || ''));
}

/** @param {number} mixId */
export async function renderStudioMix(mixId) {
	let mix = normalizeMix(
		await apiRequest(`/studio/mixes/${mixId}/render`, { method: 'POST', timeoutMs: 15_000 })
	);
	for (let attempt = 0; mix.renderStatus === 'rendering' && attempt < 240; attempt += 1) {
		await new Promise((resolve) => setTimeout(resolve, 500));
		mix = await getStudioMix(mixId);
	}
	if (mix.renderStatus === 'failed')
		throw new Error('Studio render failed. Check the source audio.');
	return mix;
}

/** @param {number} mixId */
export async function publishStudioMix(mixId) {
	return normalizeMix(await apiRequest(`/studio/mixes/${mixId}/publish`, { method: 'POST' }));
}

/** @param {number} mixId */
export async function duplicateStudioMix(mixId) {
	return normalizeMix(await apiRequest(`/studio/mixes/${mixId}/duplicate`, { method: 'POST' }));
}

/** @param {{title:string, prompt:string, mode:import('../types.js').AutoMixMode|null, limit:number}} input */
export async function autoMixFromSaved(input) {
	return normalizeMix(
		await apiRequest('/studio/auto-mix', {
			method: 'POST',
			body: JSON.stringify(input)
		})
	);
}

/** @param {'segment_replay'|'early_skip'|'mix_like'} eventType @param {number|null} savedSegmentId @param {number|null} [mixId] */
export function recordStudioBehavior(eventType, savedSegmentId, mixId = null) {
	return apiRequest('/studio/behavior', {
		method: 'POST',
		body: JSON.stringify({
			event_type: eventType,
			saved_segment_id: savedSegmentId,
			mix_id: mixId
		})
	});
}

/** @param {{role:'user'|'assistant',content:string}[]} messages @param {number|null|undefined} mixId @param {number|null|undefined} activeSavedSegmentId @param {string|null} [discoveryQuery] */
export function chatWithStudioAssistant(
	messages,
	mixId,
	activeSavedSegmentId,
	discoveryQuery = null
) {
	return apiRequest('/studio/assistant/chat', {
		method: 'POST',
		body: JSON.stringify({
			messages,
			mix_id: mixId || null,
			active_saved_segment_id: activeSavedSegmentId || null,
			discovery_query: discoveryQuery || null
		}),
		// The required 8B always-thinking model can take roughly four minutes
		// on a CPU-only host. Keep the browser ceiling just above the backend's
		// bounded 250-second timeout so the server remains the source of truth.
		timeoutMs: 265_000
	});
}

/**
 * @param {import('../types.js').StudioAssistantRecommendation} recommendation
 * @param {number|null|undefined} mixId
 * @param {import('../types.js').StudioConstraint[]} [activeConstraints]
 */
export async function applyStudioAssistantPlan(recommendation, mixId, activeConstraints = []) {
	const hasMixChanges =
		Boolean(recommendation.proposed_order) ||
		Boolean(recommendation.transition_changes?.length) ||
		Boolean(recommendation.removed_item_ids?.length) ||
		Boolean(recommendation.add_item);
	const raw = await apiRequest('/studio/assistant/apply', {
		method: 'POST',
		body: JSON.stringify({
			mix_id: hasMixChanges ? mixId || null : null,
			expected_revision: hasMixChanges ? recommendation.base_revision : null,
			proposed_order: recommendation.proposed_order,
			transition_changes: recommendation.transition_changes || [],
			segment_bound_change: recommendation.segment_bound_change,
			removed_item_ids: recommendation.removed_item_ids || [],
			add_item: recommendation.add_item || null,
			active_constraints: activeConstraints || []
		})
	});
	return {
		mix: raw?.mix ? normalizeMix(raw.mix) : null,
		savedSegment: raw?.saved_segment ? normalizeSavedSegment(raw.saved_segment) : null
	};
}
