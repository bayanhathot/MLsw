import { apiRequest } from './api.js';

/**
 * A logged-in user's own repeated-intent prompt shortcuts, ranked by
 * frequency then recency (see backend routers/profiles.py's
 * GET /me/prompt-shortcuts). Guests have no identity to key off -- callers
 * must not invoke this for a guest session.
 *
 * @returns {Promise<{ prompt: string, count: number }[]>}
 */
export function getPromptShortcuts() {
	return apiRequest('/users/me/prompt-shortcuts', {
		method: 'GET'
	});
}
