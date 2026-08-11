import { apiRequest } from './api.js';
import { normalizeMix } from './mixApi.js';

export function getMyProfile() {
	return apiRequest('/users/me/profile');
}

/** @param {{ displayName: string|null, avatarUrl: string|null, bio: string|null, favoriteGenres: string[]|null }} changes */
export function updateMyProfile(changes) {
	return apiRequest('/users/me/profile', {
		method: 'PATCH',
		body: JSON.stringify({
			display_name: changes.displayName,
			avatar_url: changes.avatarUrl,
			bio: changes.bio,
			favorite_genres: changes.favoriteGenres
		})
	});
}

export function getMyPreferences() {
	return apiRequest('/users/me/preferences');
}

/** @param {'7d'|'30d'|'6m'|'all'} [period] */
export function getMyMusicIdentity(period = 'all') {
	return apiRequest(`/users/me/music-identity?period=${period}`);
}

/** @param {'private'|'friends'|'public'|boolean} visibility */
export function updateMusicIdentityPrivacy(visibility) {
	const body = typeof visibility === 'boolean' ? { is_public: visibility } : { visibility };
	return apiRequest('/users/me/music-identity/privacy', {
		method: 'PATCH',
		body: JSON.stringify(body)
	});
}

/** @param {string} username */
export function getUserStats(username) {
	return apiRequest(`/users/${encodeURIComponent(username)}/stats`);
}

/** @param {string} username */
export function getPublicProfile(username) {
	return apiRequest(`/users/${encodeURIComponent(username)}/profile`);
}

/** @param {string} username @param {'7d'|'30d'|'6m'|'all'} [period] */
export function getPublicMusicIdentity(username, period = 'all') {
	return apiRequest(`/users/${encodeURIComponent(username)}/music-identity?period=${period}`);
}

/** @param {string} username */
export async function getPublicMixes(username) {
	const response = await apiRequest(`/users/${encodeURIComponent(username)}/mixes`);
	return Array.isArray(response) ? response.map(normalizeMix) : [];
}
