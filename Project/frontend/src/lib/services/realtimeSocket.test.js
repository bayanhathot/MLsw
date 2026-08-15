import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** Minimal fake pub/sub standing in for the real authStore -- avoids
 * pulling in its authApi.js dependency (real network calls). Mirrors the
 * one thing realtimeSocket.js actually needs: subscribe() that calls the
 * listener immediately with the current state, then again on every set(). */
function makeFakeAuthStore() {
	/** @type {Set<(state: any) => void>} */
	const subscribers = new Set();
	let state = { status: 'checking', user: null, error: null };
	return {
		/** @param {any} next */
		set(next) {
			state = next;
			for (const fn of [...subscribers]) fn(state);
		},
		/** @param {(state: any) => void} fn */
		subscribe(fn) {
			subscribers.add(fn);
			fn(state);
			return () => subscribers.delete(fn);
		}
	};
}

/** Minimal fake WebSocket standing in for the browser global. */
class FakeWebSocket {
	/** @param {string} url */
	constructor(url) {
		this.url = url;
		this.readyState = FakeWebSocket.CONNECTING;
		/** @type {string[]} */
		this.sent = [];
		/** @type {(() => void) | null} */
		this.onopen = null;
		/** @type {((event: { data: string }) => void) | null} */
		this.onmessage = null;
		/** @type {(() => void) | null} */
		this.onclose = null;
		/** @type {(() => void) | null} */
		this.onerror = null;
		FakeWebSocket.instances.push(this);
	}

	/** @param {string} data */
	send(data) {
		this.sent.push(data);
	}

	close() {
		if (this.readyState === FakeWebSocket.CLOSED) return;
		this.readyState = FakeWebSocket.CLOSED;
		this.onclose?.();
	}

	/** Test helper: simulate the server accepting the connection. */
	open() {
		this.readyState = FakeWebSocket.OPEN;
		this.onopen?.();
	}

	/** Test helper: simulate an inbound frame. @param {unknown} payload */
	receive(payload) {
		this.onmessage?.({ data: JSON.stringify(payload) });
	}
}
FakeWebSocket.CONNECTING = 0;
FakeWebSocket.OPEN = 1;
FakeWebSocket.CLOSING = 2;
FakeWebSocket.CLOSED = 3;
/** @type {FakeWebSocket[]} */
FakeWebSocket.instances = [];

function latestSocket() {
	const instance = FakeWebSocket.instances.at(-1);
	if (!instance) throw new Error('No WebSocket instance created yet.');
	return instance;
}

/** @type {ReturnType<typeof makeFakeAuthStore>} */
let fakeAuthStore;
/** @type {typeof import('./realtimeSocket.js')} */
let realtimeSocket;

beforeEach(async () => {
	vi.useFakeTimers();
	FakeWebSocket.instances = [];
	fakeAuthStore = makeFakeAuthStore();
	vi.stubGlobal('window', { location: { protocol: 'http:', host: 'localhost:5173' } });
	vi.stubGlobal('WebSocket', FakeWebSocket);
	// realtimeSocket.js decides at import time (module scope) whether to
	// start watching authStore, and keeps its connection state in module-
	// level closures -- reset the module registry and remock authStore so
	// every test gets a fully independent instance.
	vi.resetModules();
	vi.doMock('../stores/authStore.js', () => ({ authStore: fakeAuthStore }));
	realtimeSocket = await import('./realtimeSocket.js');
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.doUnmock('../stores/authStore.js');
});

describe('realtimeSocket connection lifecycle', () => {
	it('does not connect while the auth store reports no authenticated user', () => {
		fakeAuthStore.set({ status: 'guest', user: null, error: null });
		expect(FakeWebSocket.instances).toHaveLength(0);
	});

	it('connects exactly once the auth store reports an authenticated user', () => {
		fakeAuthStore.set({ status: 'checking', user: null, error: null });
		expect(FakeWebSocket.instances).toHaveLength(0);

		fakeAuthStore.set({ status: 'authenticated', user: { id: 7 }, error: null });
		expect(FakeWebSocket.instances).toHaveLength(1);
		expect(latestSocket().url).toContain('/api/ws');

		// An unrelated store update for the same user (e.g. clearError) must
		// not open a second socket.
		fakeAuthStore.set({ status: 'authenticated', user: { id: 7 }, error: 'ignored' });
		expect(FakeWebSocket.instances).toHaveLength(1);
	});
});

describe('realtimeSocket.subscribe', () => {
	it('sends a subscribe frame once open, and the returned unsubscribe sends unsubscribe', () => {
		fakeAuthStore.set({ status: 'authenticated', user: { id: 7 }, error: null });
		const socket = latestSocket();
		socket.open();

		const unsubscribe = realtimeSocket.subscribe('feed:discussion', () => {});
		expect(socket.sent.at(-1)).toBe(
			JSON.stringify({ action: 'subscribe', channel: 'feed:discussion' })
		);

		unsubscribe();
		expect(socket.sent.at(-1)).toBe(
			JSON.stringify({ action: 'unsubscribe', channel: 'feed:discussion' })
		);
	});

	it('delivers events for the subscribed channel to onEvent', () => {
		fakeAuthStore.set({ status: 'authenticated', user: { id: 7 }, error: null });
		const socket = latestSocket();
		socket.open();
		const onEvent = vi.fn();
		realtimeSocket.subscribe('post:42', onEvent);

		socket.receive({ channel: 'post:42', type: 'comment_created', data: { id: 1 } });
		expect(onEvent).toHaveBeenCalledWith('comment_created', { id: 1 });

		socket.receive({ channel: 'post:99', type: 'comment_created', data: { id: 2 } });
		expect(onEvent).toHaveBeenCalledTimes(1);
	});
});

describe('realtimeSocket onResync', () => {
	it('fires onResync on a second open but not the first', () => {
		fakeAuthStore.set({ status: 'authenticated', user: { id: 7 }, error: null });
		const firstSocket = latestSocket();
		const onResync = vi.fn();
		realtimeSocket.subscribe('feed:discussion', () => {}, { onResync });

		firstSocket.open();
		expect(onResync).not.toHaveBeenCalled();

		// Drop the connection -- a reconnect gets scheduled.
		firstSocket.close();
		vi.advanceTimersByTime(500);
		const secondSocket = latestSocket();
		expect(secondSocket).not.toBe(firstSocket);

		secondSocket.open();
		expect(onResync).toHaveBeenCalledTimes(1);
	});
});

describe('realtimeSocket.onUserEvent', () => {
	it('delivers events published on the auto-subscribed user:{id} channel only', () => {
		fakeAuthStore.set({ status: 'authenticated', user: { id: 7 }, error: null });
		const socket = latestSocket();
		socket.open();
		const onEvent = vi.fn();
		realtimeSocket.onUserEvent(onEvent);

		socket.receive({ channel: 'user:7', type: 'notification', data: { kind: 'direct_message' } });
		expect(onEvent).toHaveBeenCalledWith('notification', { kind: 'direct_message' });

		socket.receive({ channel: 'user:999', type: 'notification', data: {} });
		expect(onEvent).toHaveBeenCalledTimes(1);
	});
});

describe('realtimeSocket reconnect backoff', () => {
	it('backs off from 500ms toward the 15s cap on repeated drops', () => {
		fakeAuthStore.set({ status: 'authenticated', user: { id: 7 }, error: null });
		let socket = latestSocket();
		socket.open();

		// First drop: scheduled at the base 500ms delay.
		socket.close();
		expect(FakeWebSocket.instances).toHaveLength(1);
		vi.advanceTimersByTime(499);
		expect(FakeWebSocket.instances).toHaveLength(1);
		vi.advanceTimersByTime(1);
		expect(FakeWebSocket.instances).toHaveLength(2);

		// Second drop (never opened this time) -- delay doubles to 1000ms.
		socket = latestSocket();
		socket.close();
		vi.advanceTimersByTime(999);
		expect(FakeWebSocket.instances).toHaveLength(2);
		vi.advanceTimersByTime(1);
		expect(FakeWebSocket.instances).toHaveLength(3);

		// Keep dropping without ever reconnecting successfully: the delay
		// keeps doubling (2000, 4000, 8000ms) until it clamps at the 15s cap
		// and stays there.
		const expectedDelays = [2000, 4000, 8000, 15000, 15000];
		for (const delay of expectedDelays) {
			socket = latestSocket();
			socket.close();
			const before = FakeWebSocket.instances.length;
			vi.advanceTimersByTime(delay - 1);
			expect(FakeWebSocket.instances).toHaveLength(before);
			vi.advanceTimersByTime(1);
			expect(FakeWebSocket.instances).toHaveLength(before + 1);
		}
	});
});
