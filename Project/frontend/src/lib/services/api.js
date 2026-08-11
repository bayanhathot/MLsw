/** Shared, deployment-safe HTTP client for every frontend service. */

const DEFAULT_TIMEOUT_MS = 15_000;

/** @type {Record<string, string | undefined>} */
const publicEnvironment = import.meta.env ?? {};

/**
 * Normalize the configured backend prefix. An empty value deliberately uses
 * the same-origin Nginx/Vite proxy, which is the safest deployable default.
 *
 * @param {string | undefined} value
 */
export function normalizeApiBaseUrl(value) {
	const normalized = value?.trim() || '/api';
	return normalized === '/' ? '' : normalized.replace(/\/+$/, '');
}

export const API_BASE_URL = normalizeApiBaseUrl(publicEnvironment.PUBLIC_API_BASE_URL);

/** A structured error callers can use without parsing a message string. */
export class ApiError extends Error {
	/**
	 * @param {string} message
	 * @param {{ status?: number, code?: string, details?: unknown }} [options]
	 */
	constructor(message, { status = 0, code = 'request_failed', details = null } = {}) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		this.code = code;
		this.details = details;
	}
}

/**
 * @param {string} path
 */
export function apiUrl(path) {
	if (!path.startsWith('/')) {
		throw new TypeError('API paths must start with a slash.');
	}

	return `${API_BASE_URL}${path}`;
}

/**
 * Convert backend-hosted media URLs into URLs that work through the same
 * deployment proxy. External provider URLs are left untouched.
 *
 * @param {string | null | undefined} value
 */
export function backendMediaUrl(value) {
	if (!value) {
		return '';
	}

	if (value.startsWith('/api/')) {
		return API_BASE_URL === '/api' ? value : `${API_BASE_URL}${value.slice('/api'.length)}`;
	}

	if (value.startsWith('/static/')) {
		return apiUrl(value);
	}

	try {
		const parsed = new URL(value);
		const isDevelopmentBackend =
			(parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1') &&
			parsed.port === '5000';

		if (isDevelopmentBackend) {
			return apiUrl(`${parsed.pathname}${parsed.search}${parsed.hash}`);
		}
	} catch {
		// Relative frontend assets (for example /brand/logo.svg) stay unchanged.
	}

	return value;
}

/**
 * Turn FastAPI and generic backend error bodies into concise user-facing text.
 *
 * @param {unknown} data
 * @param {number} status
 */
function errorMessage(data, status) {
	if (data && typeof data === 'object') {
		const body = /** @type {{ detail?: unknown, message?: unknown }} */ (data);
		const detail = body.detail ?? body.message;

		if (typeof detail === 'string' && detail.trim()) {
			return detail;
		}

		if (Array.isArray(detail)) {
			const messages = detail
				.map((item) => (item && typeof item === 'object' && 'msg' in item ? String(item.msg) : ''))
				.filter(Boolean);

			if (messages.length) {
				return messages.join(' ');
			}
		}
	}

	if (typeof data === 'string' && data.trim()) {
		return data;
	}

	return `Request failed (${status}).`;
}

/**
 * @typedef {RequestInit & { timeoutMs?: number }} ApiRequestOptions
 */

/**
 * Send an HTTP request. Cookies are always included because authentication is
 * held in an HTTP-only cookie rather than browser storage.
 *
 * @param {string} path
 * @param {ApiRequestOptions} [options]
 */
export async function apiRequest(path, options = {}) {
	const {
		timeoutMs = DEFAULT_TIMEOUT_MS,
		signal: externalSignal,
		headers: requestedHeaders,
		...fetchOptions
	} = options;
	const controller = new AbortController();
	let didTimeOut = false;
	const abortFromCaller = () => controller.abort(externalSignal?.reason);

	if (externalSignal?.aborted) {
		abortFromCaller();
	} else {
		externalSignal?.addEventListener('abort', abortFromCaller, { once: true });
	}

	const timeoutId = setTimeout(() => {
		didTimeOut = true;
		controller.abort();
	}, timeoutMs);

	const headers = new Headers(requestedHeaders);
	if (
		fetchOptions.body &&
		!(fetchOptions.body instanceof FormData) &&
		!headers.has('Content-Type')
	) {
		headers.set('Content-Type', 'application/json');
	}

	try {
		const response = await fetch(apiUrl(path), {
			...fetchOptions,
			credentials: 'include',
			headers,
			signal: controller.signal
		});
		const contentType = response.headers.get('content-type') || '';
		const bodyText = response.status === 204 ? '' : await response.text();
		let data = null;

		if (bodyText) {
			if (contentType.includes('application/json')) {
				try {
					data = JSON.parse(bodyText);
				} catch {
					throw new ApiError('The server returned an invalid response.', {
						status: response.status,
						code: 'invalid_response'
					});
				}
			} else {
				data = bodyText;
			}
		}

		if (!response.ok) {
			throw new ApiError(errorMessage(data, response.status), {
				status: response.status,
				code: 'http_error',
				details: data
			});
		}

		return data;
	} catch (error) {
		if (error instanceof ApiError) {
			throw error;
		}

		if (didTimeOut) {
			throw new ApiError('The server took too long to respond. Please try again.', {
				code: 'timeout'
			});
		}

		if (controller.signal.aborted) {
			throw new ApiError('The request was cancelled.', { code: 'aborted' });
		}

		throw new ApiError('Unable to reach Zonix. Check your connection and try again.', {
			code: 'network_error',
			details: error
		});
	} finally {
		clearTimeout(timeoutId);
		externalSignal?.removeEventListener('abort', abortFromCaller);
	}
}
