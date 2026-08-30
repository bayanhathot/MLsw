#!/usr/bin/env node
/**
 * Short, bounded full-system stress gate for the production Compose stack.
 * It intentionally uses the public Caddy URL and real cookie-authenticated
 * API flows; no response is mocked and every request has a hard timeout.
 */

import { performance } from 'node:perf_hooks';

function option(name, fallback) {
	const index = process.argv.indexOf(name);
	return index >= 0 ? process.argv[index + 1] : fallback;
}

const BASE_URL = String(option('--base-url', 'https://localhost')).replace(/\/+$/, '');
const USER_COUNT = Number(option('--users', '20'));
const EXPECTED_UPLOAD_WORKERS = Number(option('--expected-upload-workers', '4'));
const INSECURE = process.argv.includes('--insecure');
const REQUEST_TIMEOUT_MS = 60_000;
const WORKLOAD_TIMEOUT_MS = 240_000;

if (!Number.isInteger(USER_COUNT) || USER_COUNT < 20 || USER_COUNT > 50 || USER_COUNT % 2) {
	throw new Error('--users must be an even integer between 20 and 50.');
}
if (!Number.isInteger(EXPECTED_UPLOAD_WORKERS) || EXPECTED_UPLOAD_WORKERS < 1) {
	throw new Error('--expected-upload-workers must be a positive integer.');
}
if (INSECURE) process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

const runId = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
const password = 'system-stress-password-1';
const responseDurations = [];
let totalResponses = 0;
let rateLimitedResponses = 0;
let serverErrors = 0;

function assert(condition, message) {
	if (!condition) throw new Error(message);
}

function delay(milliseconds) {
	return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function percentile(values, percentileValue) {
	if (!values.length) return 0;
	const ordered = [...values].sort((a, b) => a - b);
	return ordered[Math.min(ordered.length - 1, Math.floor(ordered.length * percentileValue))];
}

async function request(
	path,
	{ method = 'GET', cookie = '', json = undefined, body = undefined, expected = [200] } = {}
) {
	const headers = new Headers();
	if (cookie) headers.set('Cookie', cookie);
	if (json !== undefined) headers.set('Content-Type', 'application/json');
	const started = performance.now();
	let response;
	try {
		response = await fetch(`${BASE_URL}${path}`, {
			method,
			headers,
			body: json === undefined ? body : JSON.stringify(json),
			signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
		});
	} catch (error) {
		throw new Error(`${method} ${path} timed out or could not connect: ${error.message}`, {
			cause: error
		});
	}
	responseDurations.push(performance.now() - started);
	totalResponses += 1;
	if (response.status === 429) rateLimitedResponses += 1;
	if (response.status >= 500) serverErrors += 1;

	const text = await response.text();
	let payload = null;
	if (text) {
		try {
			payload = JSON.parse(text);
		} catch {
			payload = text;
		}
	}
	if (!expected.includes(response.status)) {
		throw new Error(
			`${method} ${path}: expected ${expected.join('/')}, received ${response.status}: ${text.slice(0, 500)}`
		);
	}
	return { response, payload };
}

function makeWav(frequency, durationSeconds = 3, sampleRate = 8000) {
	const sampleCount = durationSeconds * sampleRate;
	const dataSize = sampleCount * 2;
	const buffer = Buffer.alloc(44 + dataSize);
	buffer.write('RIFF', 0);
	buffer.writeUInt32LE(36 + dataSize, 4);
	buffer.write('WAVE', 8);
	buffer.write('fmt ', 12);
	buffer.writeUInt32LE(16, 16);
	buffer.writeUInt16LE(1, 20);
	buffer.writeUInt16LE(1, 22);
	buffer.writeUInt32LE(sampleRate, 24);
	buffer.writeUInt32LE(sampleRate * 2, 28);
	buffer.writeUInt16LE(2, 32);
	buffer.writeUInt16LE(16, 34);
	buffer.write('data', 36);
	buffer.writeUInt32LE(dataSize, 40);
	for (let index = 0; index < sampleCount; index += 1) {
		const seconds = index / sampleRate;
		const envelope = seconds % 0.4 < 0.07 ? 1 : 0.45;
		const sample = Math.sin(seconds * Math.PI * 2 * frequency) * 11_000 * envelope;
		buffer.writeInt16LE(Math.round(sample), 44 + index * 2);
	}
	return buffer;
}

function uploadBody(user, index) {
	const body = new FormData();
	body.set('batch_id', user.batchId);
	body.set('title', `Stress Pulse ${runId} ${index}`);
	body.set('album', `Stress Album ${runId}`);
	body.set('artist', user.artist);
	body.set('genre', 'Electronic');
	body.set('visibility', 'public');
	body.set(
		'file',
		new Blob([makeWav(220 + index * 7)], { type: 'audio/wav' }),
		`stress-${runId}-${index}.wav`
	);
	return body;
}

async function boundedWorkload() {
	const health = await request('/api/db-health');
	assert(health.payload.database === 'connected', 'PostgreSQL is not connected.');
	assert(health.payload.redis?.reachable === true, 'Redis is not reachable.');

	const users = Array.from({ length: USER_COUNT }, (_, index) => ({
		index,
		username: `stress_${runId}_${index}`,
		email: `stress_${runId}_${index}@example.com`,
		artist: `Stress Artist ${runId} ${index}`,
		batchId: `stress-${runId}-${index}`,
		cookie: '',
		jobId: '',
		postId: 0
	}));

	await Promise.all(
		users.map(async (user) => {
			const result = await request('/api/auth/register', {
				method: 'POST',
				json: { username: user.username, email: user.email, password },
				expected: [201]
			});
			assert(
				result.payload.username === user.username,
				`Registration mismatch for ${user.username}.`
			);
		})
	);

	const rateLimitedAt = Date.now();
	const limited = await request('/api/auth/register', {
		method: 'POST',
		json: {
			username: `stress_limited_${runId}`,
			email: `stress_limited_${runId}@example.com`,
			password
		},
		expected: [429]
	});
	const retryAfterSeconds = Number(limited.response.headers.get('retry-after'));
	assert(
		Number.isFinite(retryAfterSeconds) && retryAfterSeconds > 0,
		'429 response omitted Retry-After.'
	);

	await Promise.all(
		users.map(async (user) => {
			const result = await request('/api/auth/login', {
				method: 'POST',
				json: { email: user.email, password }
			});
			const setCookie = result.response.headers.get('set-cookie') || '';
			user.cookie = setCookie.split(';', 1)[0];
			assert(
				user.cookie.startsWith('cuemix_access_token='),
				`Login cookie missing for ${user.username}.`
			);
		})
	);

	await Promise.all(
		users.map(async (user) => {
			await request('/api/posts/feed?mode=explore&limit=5', { cookie: user.cookie });
			const post = await request('/api/posts', {
				method: 'POST',
				cookie: user.cookie,
				json: {
					title: `Stress discussion ${runId} ${user.index}`,
					body: 'Concurrent production-system stress check.',
					is_anonymous: false,
					kind: 'discussion',
					visibility: 'public',
					attachment_ids: []
				},
				expected: [201]
			});
			user.postId = Number(post.payload.id);

			const upload = await request('/api/catalog/tracks/batch-jobs', {
				method: 'POST',
				cookie: user.cookie,
				body: uploadBody(user, user.index),
				expected: [202]
			});
			user.jobId = String(upload.payload.job_id);
		})
	);

	const pairs = Array.from({ length: USER_COUNT / 2 }, (_, index) => [
		users[index * 2],
		users[index * 2 + 1]
	]);
	await Promise.all(
		pairs.map(async ([sender, recipient]) => {
			const sent = await request(`/api/friends/requests/${recipient.username}`, {
				method: 'POST',
				cookie: sender.cookie,
				expected: [201]
			});
			await request(`/api/friends/requests/${sent.payload.id}/accept`, {
				method: 'POST',
				cookie: recipient.cookie
			});
			await request('/api/messages', {
				method: 'POST',
				cookie: sender.cookie,
				json: {
					recipient_username: recipient.username,
					body: `Stress message ${runId}`,
					attachment_ids: []
				},
				expected: [201]
			});
		})
	);

	const uploadDeadline = Date.now() + 180_000;
	const terminalStatuses = new Set(['completed', 'failed', 'cancelled']);
	let latestJobs;
	do {
		latestJobs = await Promise.all(
			users.map(async (user) => {
				const result = await request(`/api/catalog/tracks/batch-jobs/${user.jobId}`, {
					cookie: user.cookie
				});
				return result.payload;
			})
		);
		if (latestJobs.every((job) => terminalStatuses.has(job.status))) break;
		await delay(500);
	} while (Date.now() < uploadDeadline);

	assert(latestJobs.length === USER_COUNT, 'Upload polling returned an incomplete result set.');
	assert(
		latestJobs.every((job) => job.status === 'completed'),
		'One or more upload jobs did not complete.'
	);

	const queue = await request('/api/admin/debug/upload-queue', { cookie: users[0].cookie });
	assert(
		queue.payload.configured_workers === EXPECTED_UPLOAD_WORKERS,
		`Expected ${EXPECTED_UPLOAD_WORKERS} upload workers, got ${queue.payload.configured_workers}.`
	);
	assert(
		queue.payload.capacity >= USER_COUNT,
		'Upload queue capacity is below the stress burst size.'
	);
	assert(queue.payload.queued_items === 0, 'Upload queue did not drain after all jobs completed.');
	assert(
		Number(queue.payload.statuses?.completed || 0) >= USER_COUNT,
		'Queue diagnostics did not retain all completed stress jobs.'
	);

	await Promise.all(
		users.map((user) =>
			request('/api/sessions/start', {
				method: 'POST',
				cookie: user.cookie,
				json: { prompt: 'energetic electronic music', mode: null }
			})
		)
	);

	const recoveryAt = rateLimitedAt + (retryAfterSeconds + 2) * 1000;
	if (Date.now() < recoveryAt) await delay(recoveryAt - Date.now());
	await request('/api/auth/register', {
		method: 'POST',
		json: {
			username: `stress_recovered_${runId}`,
			email: `stress_recovered_${runId}@example.com`,
			password
		},
		expected: [201]
	});

	assert(serverErrors === 0, `Observed ${serverErrors} unexpected 5xx responses.`);
	assert(
		rateLimitedResponses === 1,
		`Expected one deliberate 429, observed ${rateLimitedResponses}.`
	);

	return {
		users: USER_COUNT,
		requests: totalResponses,
		server_errors: serverErrors,
		rate_limited_responses: rateLimitedResponses,
		upload_workers: queue.payload.configured_workers,
		uploads_completed: latestJobs.length,
		p95_response_ms: Math.round(percentile(responseDurations, 0.95))
	};
}

const started = performance.now();
const report = await Promise.race([
	boundedWorkload(),
	new Promise((_, reject) => {
		const timer = setTimeout(
			() => reject(new Error(`System stress test exceeded ${WORKLOAD_TIMEOUT_MS} ms.`)),
			WORKLOAD_TIMEOUT_MS
		);
		timer.unref();
	})
]);
report.duration_seconds = Number(((performance.now() - started) / 1000).toFixed(1));
console.log(JSON.stringify(report, null, 2));
