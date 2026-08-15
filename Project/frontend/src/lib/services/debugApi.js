/** Internal AI-DJ pipeline / Ollama debug panel API.
 *
 * Backend-gated by ENABLE_PIPELINE_DEBUG only -- no login required (see
 * routers/debug.py's module docstring for why) -- this module never assumes
 * access; every caller must handle a 404 ApiError by simply not rendering
 * anything, the same "fail closed, no visible trace of the feature" contract
 * the backend already enforces when the flag is off.
 */

import { API_BASE_URL, apiRequest } from './api.js';

/** @returns {Promise<import('../types.js').PipelineDebugState>} */
export function getPipelineDebug() {
	return apiRequest('/debug/pipeline');
}

/** Mirrors forumApi.communityWebSocketUrl()'s same-origin/proxy-safe URL construction. */
export function pipelineDebugWebSocketUrl() {
	if (typeof window === 'undefined') return '';
	const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	if (/^https?:\/\//.test(API_BASE_URL)) {
		const url = new URL(`${API_BASE_URL}/debug/ws`);
		url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
		return url.toString();
	}
	return `${protocol}//${window.location.host}${API_BASE_URL}/debug/ws`;
}
