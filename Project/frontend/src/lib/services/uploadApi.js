import { apiRequest, backendMediaUrl } from './api.js';

/** @param {unknown} value */
export function normalizeUploadedAttachment(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	return {
		...raw,
		url: backendMediaUrl(String(raw.url || ''))
	};
}

/** @param {File} file @param {{ signal?: AbortSignal, priority?: number }} [options] */
export function enqueueUpload(file, { signal, priority = 5 } = {}) {
	return apiRequest(`/uploads/jobs?priority=${priority}`, {
		method: 'POST',
		body: file,
		headers: {
			'Content-Type': file.type,
			'X-Filename': encodeURIComponent(file.name)
		},
		timeoutMs: 60_000,
		signal
	});
}

/** @param {string} jobId @param {{ signal?: AbortSignal }} [options] */
export function getUploadJob(jobId, { signal } = {}) {
	return apiRequest(`/uploads/jobs/${encodeURIComponent(jobId)}`, { signal });
}

/** @param {number} attachmentId */
export function deleteAttachment(attachmentId) {
	return apiRequest(`/uploads/${attachmentId}`, { method: 'DELETE' });
}

/** @param {File} file @param {{ signal?: AbortSignal, priority?: number }} [options] */
export async function uploadAndWait(file, { signal, priority = 5 } = {}) {
	let job = /** @type {Record<string, any>} */ (await enqueueUpload(file, { signal, priority }));
	for (
		let attempt = 0;
		attempt < 60 && !['completed', 'failed'].includes(job.status);
		attempt += 1
	) {
		await new Promise((resolve) => setTimeout(resolve, 500));
		if (signal?.aborted) throw new DOMException('Upload cancelled.', 'AbortError');
		job = /** @type {Record<string, any>} */ (await getUploadJob(String(job.job_id), { signal }));
	}

	if (job.status === 'failed') throw new Error(String(job.error || 'The upload failed.'));
	if (job.status !== 'completed' || !job.attachment)
		throw new Error('The upload is still processing.');
	return normalizeUploadedAttachment(job.attachment);
}
