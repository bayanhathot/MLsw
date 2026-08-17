/** Bulk catalog-track upload: one multipart request per file, tagged with a
 * shared batchId, polled for status/progress. See backend/app/routers/
 * catalog.py's module docstring for the full contract. */

import { apiRequest, backendMediaUrl } from './api.js';

/** @param {unknown} value */
export function normalizeCatalogTrack(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	return {
		id: Number(raw.id),
		title: String(raw.title || ''),
		artist: String(raw.artist || ''),
		album: raw.album ?? null,
		genre: raw.genre ?? null,
		lyrics: raw.lyrics ?? null,
		visibility: raw.visibility === 'public' ? 'public' : 'private',
		durationSeconds: Number(raw.duration_seconds || 0),
		analysisStatus: String(raw.analysis_status || 'pending'),
		audioUrl: backendMediaUrl(String(raw.audio_url || '')),
		createdAt: String(raw.created_at || '')
	};
}

/** @param {unknown} value */
export function normalizeCatalogJob(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	return {
		jobId: String(raw.job_id || ''),
		batchId: String(raw.batch_id || ''),
		filename: String(raw.filename || ''),
		status: String(raw.status || 'queued'),
		priority: Number(raw.priority || 0),
		track: raw.track ? normalizeCatalogTrack(raw.track) : null,
		error: raw.error ?? null
	};
}

/**
 * @param {{ batchId: string, file: File, title?: string, artist: string, album: string, genre?: string, lyrics?: string, visibility?: 'private'|'public', signal?: AbortSignal }} input
 */
export async function enqueueCatalogTrack({
	batchId,
	file,
	title,
	artist,
	album,
	genre,
	lyrics,
	visibility = 'private',
	signal
}) {
	const form = new FormData();
	form.set('batch_id', batchId);
	form.set('artist', artist);
	form.set('album', album);
	if (title) form.set('title', title);
	if (genre) form.set('genre', genre);
	if (lyrics) form.set('lyrics', lyrics);
	form.set('visibility', visibility);
	form.set('file', file, file.name);

	return normalizeCatalogJob(
		await apiRequest('/catalog/tracks/batch-jobs', {
			method: 'POST',
			body: form,
			timeoutMs: 120_000,
			signal
		})
	);
}

/** @param {string} batchId @param {{ signal?: AbortSignal }} [options] */
export async function getCatalogBatchStatus(batchId, { signal } = {}) {
	const raw = /** @type {Record<string, any>} */ (
		await apiRequest(`/catalog/tracks/batches/${encodeURIComponent(batchId)}`, { signal })
	);
	return {
		batchId: String(raw.batch_id || batchId),
		total: Number(raw.total || 0),
		queued: Number(raw.queued || 0),
		processing: Number(raw.processing || 0),
		completed: Number(raw.completed || 0),
		failed: Number(raw.failed || 0),
		jobs: Array.isArray(raw.jobs) ? raw.jobs.map(normalizeCatalogJob) : []
	};
}
