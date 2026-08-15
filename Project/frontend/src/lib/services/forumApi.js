/** Public forum API: posts, comments, and reversible votes. */

import { apiRequest, backendMediaUrl } from './api.js';

/** @param {unknown} value @returns {'discussion'|'status'|'mix_share'} */
function normalizePostKind(value) {
	return value === 'status' || value === 'mix_share' ? value : 'discussion';
}

/** @param {unknown} value @returns {'public'|'friends'} */
function normalizeVisibility(value) {
	return value === 'friends' ? 'friends' : 'public';
}

/** @param {unknown} value */
function normalizeAttachment(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	return {
		id: Number(raw.id),
		kind: String(raw.kind || ''),
		filename: String(raw.filename || ''),
		contentType: String(raw.content_type ?? raw.contentType ?? ''),
		url: backendMediaUrl(String(raw.url || '')),
		sizeBytes: Number(raw.size_bytes ?? raw.sizeBytes ?? 0)
	};
}

/** @param {unknown} value @returns {import('../types.js').ForumPost} */
export function normalizePost(value) {
	if (!value || typeof value !== 'object')
		throw new TypeError('The server returned an invalid post.');
	const raw = /** @type {Record<string, any>} */ (value);
	return {
		id: Number(raw.id),
		authorId: raw.author_id == null ? null : Number(raw.author_id),
		authorUsername: String(raw.author_username || 'Anonymous'),
		title: String(raw.title || 'Untitled'),
		body: String(raw.body || ''),
		isAnonymous: Boolean(raw.is_anonymous),
		kind: normalizePostKind(raw.kind),
		visibility: normalizeVisibility(raw.visibility),
		mix:
			raw.mix && typeof raw.mix === 'object'
				? {
						id: Number(raw.mix.id),
						title: String(raw.mix.title || ''),
						prompt: String(raw.mix.prompt || ''),
						coverUrl: String(raw.mix.cover_url || ''),
						ownerUsername: String(raw.mix.owner_username || ''),
						segmentCount: Number(raw.mix.segment_count || 0)
					}
				: null,
		canDelete: Boolean(raw.can_delete ?? raw.canDelete),
		score: Number(raw.score || 0),
		commentCount: Number(raw.comment_count || 0),
		myVote: Number(raw.my_vote || 0),
		attachments: Array.isArray(raw.attachments) ? raw.attachments.map(normalizeAttachment) : [],
		createdAt: String(raw.created_at || '')
	};
}

/** @param {unknown} value @returns {import('../types.js').ForumComment} */
export function normalizeComment(value) {
	if (!value || typeof value !== 'object')
		throw new TypeError('The server returned an invalid comment.');
	const raw = /** @type {Record<string, any>} */ (value);
	return {
		id: Number(raw.id),
		authorId: raw.author_id == null ? null : Number(raw.author_id),
		authorUsername: String(raw.author_username || 'Anonymous'),
		body: String(raw.body || ''),
		isAnonymous: Boolean(raw.is_anonymous),
		canDelete: Boolean(raw.can_delete ?? raw.canDelete),
		score: Number(raw.score || 0),
		myVote: Number(raw.my_vote || 0),
		attachments: Array.isArray(raw.attachments) ? raw.attachments.map(normalizeAttachment) : [],
		createdAt: String(raw.created_at || '')
	};
}

/** @param {{ limit?: number, offset?: number, mode?: 'explore'|'friends'|'discussions', signal?: AbortSignal }} [options] */
export async function getPosts({ limit = 10, offset = 0, mode = 'explore', signal } = {}) {
	const response = await apiRequest(
		`/posts/feed?mode=${encodeURIComponent(mode)}&limit=${limit}&offset=${offset}`,
		{ signal }
	);
	if (!Array.isArray(response)) throw new TypeError('The server returned an invalid forum feed.');
	return response.map(normalizePost);
}

/** @param {number} postId */
export function deletePost(postId) {
	return apiRequest(`/posts/${postId}`, { method: 'DELETE' });
}

/** @param {{ title?: string, body: string, isAnonymous?: boolean, attachmentIds?: number[], kind?: 'discussion'|'status'|'mix_share', visibility?: 'public'|'friends', mixId?: number|null }} input */
export async function createPost(input) {
	return normalizePost(
		await apiRequest('/posts', {
			method: 'POST',
			body: JSON.stringify({
				title: input.title || null,
				body: input.body,
				is_anonymous: Boolean(input.isAnonymous),
				kind: input.kind || 'discussion',
				visibility: input.visibility || 'public',
				mix_id: input.mixId || null,
				attachment_ids: input.attachmentIds || []
			})
		})
	);
}

/** @param {number} postId @param {-1 | 0 | 1} value */
export async function votePost(postId, value) {
	return normalizePost(
		await apiRequest(`/posts/${postId}/vote`, {
			method: value === 0 ? 'DELETE' : 'POST',
			...(value === 0 ? {} : { body: JSON.stringify({ value }) })
		})
	);
}

/** @param {number} postId @param {{ signal?: AbortSignal }} [options] */
export async function getComments(postId, { signal } = {}) {
	const response = await apiRequest(`/posts/${postId}/comments`, { signal });
	if (!Array.isArray(response)) throw new TypeError('The server returned invalid comments.');
	return response.map(normalizeComment);
}

/** @param {number} postId @param {{ body: string, isAnonymous: boolean, attachmentIds?: number[] }} input */
export async function createComment(postId, input) {
	return normalizeComment(
		await apiRequest(`/posts/${postId}/comments`, {
			method: 'POST',
			body: JSON.stringify({
				body: input.body,
				is_anonymous: input.isAnonymous,
				attachment_ids: input.attachmentIds || []
			})
		})
	);
}

/** @param {number} postId @param {number} commentId */
export function deleteComment(postId, commentId) {
	return apiRequest(`/posts/${postId}/comments/${commentId}`, { method: 'DELETE' });
}

/** @param {number} commentId @param {-1 | 0 | 1} value */
export async function voteComment(commentId, value) {
	return normalizeComment(
		await apiRequest(`/posts/comments/${commentId}/vote`, {
			method: value === 0 ? 'DELETE' : 'POST',
			...(value === 0 ? {} : { body: JSON.stringify({ value }) })
		})
	);
}
