/** Admin debug dashboard API (routers/admin_debug.py), reachable by any
 * logged-in account.
 *
 * Backend-gated by DEBUG_DASHBOARD_ENABLED plus requiring a logged-in
 * session -- every caller must handle a 404 ApiError by simply not
 * rendering anything, the same "fail closed, no visible trace of the
 * feature" contract debugApi.js already documents for the other
 * (unauthenticated) debug panel. A 404 here additionally means "you are
 * not logged in," not just "the feature is off" -- the backend
 * deliberately makes those indistinguishable.
 */

import { apiRequest } from './api.js';

/** @returns {Promise<{ sessions: Array<Record<string, any>> }>} */
export function getAdminDebugSessions() {
	return apiRequest('/admin/debug/sessions');
}

/** @param {string} [search] @returns {Promise<{ tracks: Array<Record<string, any>> }>} */
export function getAdminDebugExternalTracks(search) {
	const query = search && search.trim() ? `?search=${encodeURIComponent(search.trim())}` : '';
	return apiRequest(`/admin/debug/external-tracks${query}`);
}

/** @returns {Promise<{ events: Array<Record<string, any>> }>} */
export function getAdminDebugEvents() {
	return apiRequest('/admin/debug/events');
}
