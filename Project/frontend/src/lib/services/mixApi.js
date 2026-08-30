/** API functions and response normalization for persistent community mixes. */

import { apiRequest, backendMediaUrl } from './api.js';
import { normalizeSegment } from './segment.js';
import { isAutoMixMode } from '../constants/autoMixModes.js';

/**
 * @param {unknown} value
 * @returns {import('../types.js').Mix}
 */
export function normalizeMix(value) {
	if (!value || typeof value !== 'object') {
		throw new TypeError('The server returned an invalid mix.');
	}

	const raw = /** @type {Record<string, any>} */ (value);
	const segments = Array.isArray(raw.segments) ? raw.segments.map(normalizeSegment) : [];

	return {
		id: Number(raw.id),
		sessionId: String(raw.sessionId ?? raw.session_id ?? raw.id ?? ''),
		title: String(raw.title || 'Untitled mix'),
		prompt: String(raw.prompt || ''),
		mode: isAutoMixMode(raw.mode) ? raw.mode : null,
		description: typeof raw.description === 'string' ? raw.description : null,
		coverUrl: String(raw.coverUrl ?? raw.cover_url ?? segments[0]?.coverUrl ?? ''),
		status: raw.status === 'published' ? 'published' : 'draft',
		createdAt: String(raw.createdAt ?? raw.created_at ?? ''),
		publishedAt: raw.publishedAt ?? raw.published_at ?? null,
		isStudio: Boolean(raw.isStudio ?? raw.is_studio),
		revision: Number(raw.revision || 1),
		renderedRevision: raw.rendered_revision == null ? null : Number(raw.rendered_revision),
		publishedRevision: raw.published_revision == null ? null : Number(raw.published_revision),
		renderStatus: String(raw.render_status || 'not_rendered'),
		renderedAudioUrl: raw.rendered_audio_url ? String(raw.rendered_audio_url) : null,
		publishedAudioUrl: raw.published_audio_url ? String(raw.published_audio_url) : null,
		publicationMode: ['rendered_asset', 'provider_manifest'].includes(
			raw.publicationMode ?? raw.publication_mode
		)
			? (raw.publicationMode ?? raw.publication_mode)
			: null,
		visibility: raw.visibility === 'public' ? 'public' : 'private',
		segments,
		owner:
			raw.owner && typeof raw.owner === 'object'
				? { id: Number(raw.owner.id), username: String(raw.owner.username || 'unknown') }
				: null,
		likeCount: Number(raw.likeCount ?? raw.like_count ?? 0),
		isLiked: Boolean(raw.isLiked ?? raw.is_liked),
		isSaved: Boolean(raw.isSaved ?? raw.is_saved)
	};
}

/** @param {{ limit?: number, offset?: number, signal?: AbortSignal }} [options] */
export async function getFeed({ limit = 20, offset = 0, signal } = {}) {
	const response = await apiRequest(`/mixes/feed?limit=${limit}&offset=${offset}`, { signal });
	if (!Array.isArray(response)) {
		throw new TypeError('The server returned an invalid feed.');
	}
	return response.map(normalizeMix);
}

/** @param {{ signal?: AbortSignal }} [options] */
export async function getLibrary({ signal } = {}) {
	const response = await apiRequest('/mixes/library', { signal });
	if (!response || typeof response !== 'object') {
		throw new TypeError('The server returned an invalid library.');
	}
	const library = /** @type {Record<string, unknown>} */ (response);
	return {
		owned: Array.isArray(library.owned) ? library.owned.map(normalizeMix) : [],
		saved: Array.isArray(library.saved) ? library.saved.map(normalizeMix) : []
	};
}

/** @param {number} mixId */
export async function getMix(mixId) {
	return normalizeMix(await apiRequest(`/mixes/${mixId}`));
}

/**
 * @param {unknown} value
 * @returns {import('../types.js').PlaybackManifestSegment}
 */
function normalizeManifestSegment(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	return {
		position: Number(raw.position || 0),
		title: String(raw.title || ''),
		artist: String(raw.artist || ''),
		coverUrl: raw.cover_url ? String(raw.cover_url) : null,
		source: String(raw.source || ''),
		sourceTrackId: String(raw.source_track_id || ''),
		audioUrl: raw.audio_url ? backendMediaUrl(String(raw.audio_url)) : null,
		startMs: Number(raw.start_ms || 0),
		endMs: Number(raw.end_ms || 0),
		transitionType: String(raw.transition_type || 'cut'),
		transitionDurationMs: Number(raw.transition_duration_ms || 0),
		gainDb: raw.gain_db == null ? null : Number(raw.gain_db),
		providerUrl: raw.provider_url ? String(raw.provider_url) : null,
		attribution: raw.attribution ? String(raw.attribution) : null,
		license: raw.license ? String(raw.license) : null,
		rightsStatus: String(raw.rights_status || 'creator_owned'),
		availability: raw.availability === 'unavailable' ? 'unavailable' : 'available',
		unavailableReason: raw.unavailable_reason ? String(raw.unavailable_reason) : null
	};
}

/**
 * @param {unknown} value
 * @returns {import('../types.js').PlaybackManifest}
 */
export function normalizePlaybackManifest(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	const segments = Array.isArray(raw.segments) ? raw.segments.map(normalizeManifestSegment) : [];
	return {
		schemaVersion: Number(raw.schema_version || 1),
		mixId: Number(raw.mix_id),
		revision: Number(raw.revision || 1),
		mode: raw.mode === 'provider_manifest' ? 'provider_manifest' : 'rendered_asset',
		title: String(raw.title || ''),
		audioUrl: raw.audio_url ? backendMediaUrl(String(raw.audio_url)) : null,
		segments: segments.sort((a, b) => a.position - b.position)
	};
}

/** @param {number} mixId */
export async function getPlaybackManifest(mixId) {
	return normalizePlaybackManifest(await apiRequest(`/mixes/${mixId}/playback-manifest`));
}

/** @param {string} prompt @param {import('../types.js').AutoMixMode | null} [mode] */
export async function createMix(prompt, mode = null) {
	return normalizeMix(
		await apiRequest('/mixes/start', {
			method: 'POST',
			body: JSON.stringify({ prompt, mode })
		})
	);
}

/** @param {number} mixId */
export function likeMix(mixId) {
	return apiRequest(`/mixes/${mixId}/like`, { method: 'POST' });
}

/** @param {number} mixId */
export function unlikeMix(mixId) {
	return apiRequest(`/mixes/${mixId}/like`, { method: 'DELETE' });
}

/** @param {number} mixId */
export function saveMix(mixId) {
	return apiRequest(`/mixes/${mixId}/save`, { method: 'POST' });
}

/** @param {number} mixId */
export function unsaveMix(mixId) {
	return apiRequest(`/mixes/${mixId}/save`, { method: 'DELETE' });
}

/** @param {number} mixId */
export async function publishMix(mixId) {
	return normalizeMix(await apiRequest(`/mixes/${mixId}/publish`, { method: 'POST' }));
}

/**
 * @param {number} mixId
 * @param {{ title: string, description: string | null, coverUrl: string | null }} changes
 */
export async function updateMix(mixId, changes) {
	return normalizeMix(
		await apiRequest(`/mixes/${mixId}`, {
			method: 'PATCH',
			body: JSON.stringify({
				title: changes.title,
				description: changes.description,
				cover_url: changes.coverUrl
			})
		})
	);
}
