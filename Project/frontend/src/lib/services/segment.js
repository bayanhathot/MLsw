/** Shared segment normalization for the `/sessions` and `/mixes` adapters.
 *
 * A session and a persisted mix both carry the same segment shape from the
 * backend (AI-DJ pipeline output vs. a saved copy of it), so both accept
 * either camelCase or snake_case field names and normalize identically.
 */

import { backendMediaUrl } from './api.js';

/**
 * @param {unknown} value
 * @param {string} [fallback]
 */
function text(value, fallback = '') {
	return typeof value === 'string' && value.trim() ? value : fallback;
}

/** @param {unknown} value */
function nullableNumber(value) {
	if (value === null || value === undefined || value === '') return null;
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : null;
}

/**
 * @param {Record<string, any>} segment
 * @param {number} index
 * @returns {import('../types.js').SessionSegment}
 */
export function normalizeSegment(segment, index) {
	return {
		id: segment.id ?? index,
		position: Number(segment.position ?? index + 1),
		title: text(segment.title, `Segment ${index + 1}`),
		artist: text(segment.artist, 'Unknown artist'),
		audioUrl: backendMediaUrl(text(segment.audioUrl ?? segment.audio_url)),
		coverUrl: text(segment.coverUrl ?? segment.cover_url),
		startSecond: Number(segment.startSecond ?? segment.start_second ?? 0),
		endSecond: Number(segment.endSecond ?? segment.end_second ?? 0),
		transitionToNext: text(segment.transitionToNext ?? segment.transition_to_next, 'crossfade'),
		source: text(segment.source),
		sourceTrackId: text(segment.sourceTrackId ?? segment.source_track_id),
		trackDurationSeconds: nullableNumber(
			segment.trackDurationSeconds ?? segment.track_duration_seconds
		),
		genre: text(segment.genre),
		vibe: text(segment.vibe),
		savedSegmentId: nullableNumber(segment.savedSegmentId ?? segment.saved_segment_id),
		sourceAudioUrl: backendMediaUrl(
			text(segment.sourceAudioUrl ?? segment.source_audio_url ?? segment.audio_url)
		),
		sourceStartMs: nullableNumber(segment.sourceStartMs ?? segment.source_start_ms),
		sourceEndMs: nullableNumber(segment.sourceEndMs ?? segment.source_end_ms),
		bpm: nullableNumber(segment.bpm),
		musicalKey: text(segment.musicalKey ?? segment.musical_key),
		camelot: text(segment.camelot),
		transitionType: text(segment.transitionType ?? segment.transition_type, 'crossfade'),
		transitionDurationMs: Number(
			segment.transitionDurationMs ?? segment.transition_duration_ms ?? 4000
		),
		compatibilityScore: nullableNumber(segment.compatibilityScore ?? segment.compatibility_score),
		compatibilityFactors: segment.compatibilityFactors ?? segment.compatibility_factors_json ?? null
	};
}
