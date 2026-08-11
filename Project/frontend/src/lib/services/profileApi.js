import { apiRequest } from './api.js';

export function getMyProfile() {
	return apiRequest('/users/me/profile');
}

/**
 * @param {{
 *  displayName: string | null,
 *  avatarUrl: string | null,
 *  bio: string | null,
 *  favoriteGenres: string[] | null,
 *  themePreference: 'dark' | 'light' | 'system'
 * }} changes
 */
export function updateMyProfile(changes) {
	return apiRequest('/users/me/profile', {
		method: 'PATCH',
		body: JSON.stringify({
			display_name: changes.displayName,
			avatar_url: changes.avatarUrl,
			bio: changes.bio,
			favorite_genres: changes.favoriteGenres,
			theme_preference: changes.themePreference
		})
	});
}

export function getMyPreferences() {
	return apiRequest('/users/me/preferences');
}

/** @param {string} username */
export function getUserStats(username) {
	return apiRequest(`/users/${encodeURIComponent(username)}/stats`);
}
