import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiRequest, backendMediaUrl, normalizeApiBaseUrl } from './api.js';
import { enqueueUpload } from './uploadApi.js';

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('shared API client', () => {
	it('uses a same-origin API prefix by default', () => {
		expect(normalizeApiBaseUrl(undefined)).toBe('/api');
		expect(normalizeApiBaseUrl(' https://api.example.test/ ')).toBe('https://api.example.test');
	});

	it('rewrites only local backend media through the deployment proxy', () => {
		expect(backendMediaUrl('http://localhost:5000/static/audio/demo.mp3')).toBe(
			'/api/static/audio/demo.mp3'
		);
		expect(backendMediaUrl('https://provider.example/stream/1')).toBe(
			'https://provider.example/stream/1'
		);
	});

	it('includes cookie credentials and parses successful JSON', async () => {
		const fetchMock = vi.fn().mockResolvedValue(
			new Response(JSON.stringify({ ok: true }), {
				status: 200,
				headers: { 'content-type': 'application/json' }
			})
		);
		vi.stubGlobal('fetch', fetchMock);

		await expect(apiRequest('/health')).resolves.toEqual({ ok: true });
		expect(fetchMock).toHaveBeenCalledWith(
			'/api/health',
			expect.objectContaining({ credentials: 'include' })
		);
	});

	it('encodes Unicode upload filenames into a ByteString-safe header', async () => {
		const fetchMock = vi.fn().mockResolvedValue(
			new Response(JSON.stringify({ job_id: 'job-1', status: 'queued' }), {
				status: 200,
				headers: { 'content-type': 'application/json' }
			})
		);
		vi.stubGlobal('fetch', fetchMock);
		const file = /** @type {File} */ (
			/** @type {unknown} */ ({ name: 'موسيقى 🎵.mp3', type: 'audio/mpeg' })
		);

		await enqueueUpload(file);

		const headers = /** @type {Headers} */ (fetchMock.mock.calls[0][1].headers);
		expect(headers.get('X-Filename')).toBe(encodeURIComponent(file.name));
	});

	it('preserves FastAPI validation details in a structured error', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(
				new Response(JSON.stringify({ detail: [{ msg: 'Prompt cannot be blank.' }] }), {
					status: 422,
					headers: { 'content-type': 'application/json' }
				})
			)
		);

		const request = apiRequest('/sessions/start', {
			method: 'POST',
			body: JSON.stringify({ prompt: '' })
		});
		await expect(request).rejects.toMatchObject({
			name: 'ApiError',
			status: 422,
			message: 'Prompt cannot be blank.'
		});
		await request.catch((error) => expect(error).toBeInstanceOf(ApiError));
	});
});
