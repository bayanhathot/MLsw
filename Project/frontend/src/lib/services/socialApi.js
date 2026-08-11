import { apiRequest } from './api.js';

/** @param {unknown} value @returns {import('../types.js').SocialUser} */
export function normalizeUserCard(value) {
	const raw = /** @type {Record<string, any>} */ (value || {});
	return {
		id: Number(raw.id),
		username: String(raw.username || ''),
		displayName: raw.display_name == null ? null : String(raw.display_name),
		avatarUrl: raw.avatar_url == null ? null : String(raw.avatar_url),
		bio: raw.bio == null ? null : String(raw.bio),
		musicInterests: Array.isArray(raw.music_interests) ? raw.music_interests.map(String) : [],
		friendCount: Number(raw.friend_count || 0),
		mutualFriendCount: Number(raw.mutual_friend_count || 0),
		relationshipStatus: String(raw.relationship_status || 'none')
	};
}

/** @param {string} query */
export async function searchUsers(query) {
	const response = await apiRequest(`/users/search?q=${encodeURIComponent(query)}`);
	return Array.isArray(response) ? response.map(normalizeUserCard) : [];
}

export async function discoverUsers() {
	const response = await apiRequest('/users/discover');
	return Array.isArray(response) ? response.map(normalizeUserCard) : [];
}

export async function getFriends() {
	const response = await apiRequest('/friends');
	return Array.isArray(response) ? response.map(normalizeUserCard) : [];
}

/** @param {string} username */
export async function getPublicFriends(username) {
	const response = await apiRequest(`/users/${encodeURIComponent(username)}/friends`);
	return Array.isArray(response) ? response.map(normalizeUserCard) : [];
}

/** @returns {Promise<import('../types.js').FriendRequestEntry[]>} */
export async function getFriendRequests() {
	const response = await apiRequest('/friends/requests');
	return Array.isArray(response) ? response : [];
}

/** @param {string} username */
export function sendFriendRequest(username) {
	return apiRequest(`/friends/requests/${encodeURIComponent(username)}`, { method: 'POST' });
}

/** @param {string} username */
export function cancelFriendRequest(username) {
	return apiRequest(`/friends/requests/${encodeURIComponent(username)}`, { method: 'DELETE' });
}

/** @param {number} requestId */
export function acceptFriendRequest(requestId) {
	return apiRequest(`/friends/requests/${requestId}/accept`, { method: 'POST' });
}

/** @param {number} requestId */
export function declineFriendRequest(requestId) {
	return apiRequest(`/friends/requests/${requestId}/decline`, { method: 'POST' });
}

/** @param {string} username */
export function removeFriend(username) {
	return apiRequest(`/friends/${encodeURIComponent(username)}`, { method: 'DELETE' });
}

/** @param {string} username */
export function blockUser(username) {
	return apiRequest(`/users/${encodeURIComponent(username)}/block`, { method: 'POST' });
}

/** @param {string} username */
export function unblockUser(username) {
	return apiRequest(`/users/${encodeURIComponent(username)}/block`, { method: 'DELETE' });
}

/** @param {'user'|'post'|'comment'} targetType @param {number} targetId @param {string} reason @param {string} [details] */
export function reportContent(targetType, targetId, reason, details = '') {
	return apiRequest('/reports', {
		method: 'POST',
		body: JSON.stringify({
			target_type: targetType,
			target_id: targetId,
			reason,
			details: details || null
		})
	});
}
