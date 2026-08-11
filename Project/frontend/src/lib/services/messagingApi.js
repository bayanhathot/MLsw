import { API_BASE_URL, apiRequest, backendMediaUrl } from './api.js';

/** @param {unknown} value */
function normalizeAttachment(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	return {
		...raw,
		id: Number(raw.id),
		kind: String(raw.kind || ''),
		filename: String(raw.filename || ''),
		url: backendMediaUrl(String(raw.url || ''))
	};
}

/** @param {unknown} value */
export function normalizeMessage(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	return {
		id: Number(raw.id),
		sender_id: Number(raw.sender_id),
		sender_username: String(raw.sender_username || ''),
		recipient_id: Number(raw.recipient_id),
		recipient_username: String(raw.recipient_username || ''),
		body: String(raw.body || ''),
		attachments: Array.isArray(raw.attachments) ? raw.attachments.map(normalizeAttachment) : [],
		created_at: String(raw.created_at || ''),
		read_at: raw.read_at == null ? null : String(raw.read_at)
	};
}

/** @param {unknown} value */
export function normalizeNotification(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	return {
		id: Number(raw.id),
		kind: String(raw.kind || ''),
		message: String(raw.message || ''),
		entity_type: raw.entity_type == null ? null : String(raw.entity_type),
		entity_id: raw.entity_id == null ? null : Number(raw.entity_id),
		is_read: Boolean(raw.is_read),
		created_at: String(raw.created_at || ''),
		direct_message: raw.direct_message ? normalizeMessage(raw.direct_message) : null
	};
}

/** @param {{ signal?: AbortSignal }} [options] */
export async function getConversations({ signal } = {}) {
	const response = await apiRequest('/conversations', { signal });
	if (!Array.isArray(response)) throw new TypeError('The server returned invalid conversations.');
	return response.map((raw) => ({
		username: String(raw.username || ''),
		displayName: raw.display_name == null ? null : String(raw.display_name),
		avatarUrl: raw.avatar_url == null ? null : String(raw.avatar_url),
		lastMessage: String(raw.last_message || ''),
		lastMessageAt: String(raw.last_message_at || ''),
		unreadCount: Number(raw.unread_count || 0)
	}));
}

/** @param {string} username @param {{ signal?: AbortSignal }} [options] */
export async function getConversation(username, { signal } = {}) {
	const response = await apiRequest(`/messages/${encodeURIComponent(username)}`, { signal });
	if (!Array.isArray(response)) throw new TypeError('The server returned an invalid conversation.');
	return response.map(normalizeMessage);
}

/** @param {{ recipientUsername: string, body: string, attachmentIds?: number[] }} input */
export async function sendDirectMessage(input) {
	return normalizeMessage(
		await apiRequest('/messages', {
			method: 'POST',
			body: JSON.stringify({
				recipient_username: input.recipientUsername,
				body: input.body,
				attachment_ids: input.attachmentIds || []
			})
		})
	);
}

/** @param {{ signal?: AbortSignal }} [options] */
export async function getNotifications({ signal } = {}) {
	const response = await apiRequest('/notifications', { signal });
	if (!Array.isArray(response)) throw new TypeError('The server returned invalid notifications.');
	return response.map(normalizeNotification);
}

/** @param {number} notificationId */
export async function markNotificationRead(notificationId) {
	return normalizeNotification(
		await apiRequest(`/notifications/${notificationId}/read`, { method: 'POST' })
	);
}

export function notificationWebSocketUrl() {
	if (typeof window === 'undefined') return '';
	const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	if (/^https?:\/\//.test(API_BASE_URL)) {
		const url = new URL(`${API_BASE_URL}/ws/notifications`);
		url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
		return url.toString();
	}
	return `${protocol}//${window.location.host}${API_BASE_URL}/ws/notifications`;
}
