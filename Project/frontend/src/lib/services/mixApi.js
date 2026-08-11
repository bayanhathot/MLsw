/** API functions and response normalization for persistent community mixes. */

import { apiRequest, backendMediaUrl } from './api.js';

/**
 * @param {unknown} value
 * @returns {import('../types.js').Mix}
 */
export function normalizeMix(value) {
	if (!value || typeof value !== 'object') {
		throw new TypeError('The server returned an invalid mix.');
	}

	const raw = /** @type {Record<string, any>} */ (value);
	const segments = Array.isArray(raw.segments)
		? raw.segments.map((segment, index) => ({
				id: segment.id ?? index,
				position: Number(segment.position ?? index + 1),
				title: String(segment.title || `Segment ${index + 1}`),
				artist: String(segment.artist || 'Unknown artist'),
				audioUrl: backendMediaUrl(segment.audioUrl ?? segment.audio_url),
				coverUrl: String(segment.coverUrl ?? segment.cover_url ?? ''),
				startSecond: Number(segment.startSecond ?? segment.start_second ?? 0),
				endSecond: Number(segment.endSecond ?? segment.end_second ?? 0),
				transitionToNext: String(
					segment.transitionToNext ?? segment.transition_to_next ?? 'crossfade'
				),
				source: String(segment.source ?? ''),
				sourceTrackId: String(segment.sourceTrackId ?? segment.source_track_id ?? '')
			}))
		: [];

	return {
		id: Number(raw.id),
		sessionId: String(raw.sessionId ?? raw.session_id ?? raw.id ?? ''),
		title: String(raw.title || 'Untitled mix'),
		prompt: String(raw.prompt || ''),
		description: typeof raw.description === 'string' ? raw.description : null,
		coverUrl: String(raw.coverUrl ?? raw.cover_url ?? segments[0]?.coverUrl ?? ''),
		status: raw.status === 'published' ? 'published' : 'draft',
		createdAt: String(raw.createdAt ?? raw.created_at ?? ''),
		publishedAt: raw.publishedAt ?? raw.published_at ?? null,
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

/** @param {string} prompt */
export async function createMix(prompt) {
	return normalizeMix(
		await apiRequest('/mixes/start', {
			method: 'POST',
			body: JSON.stringify({ prompt })
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
