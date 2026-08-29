/**
 * Single realtime WebSocket client for the whole app (GET /ws, see backend
 * app/routers/realtime.py + app/services/channel_hub.py) -- one connection
 * that fans typed events out to whichever components have asked for them.
 *
 * Connection lifecycle is owned entirely here, driven by authStore: one
 * socket opens on login and closes on logout, so components never manage a
 * WebSocket directly -- they just subscribe()/unsubscribe() channel names.
 */

import { writable } from 'svelte/store';

import { API_BASE_URL } from './api.js';
import { authStore } from '../stores/authStore.js';

const BASE_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 15_000;

/**
 * 'connecting' | 'open' | 'reconnecting' | 'closed' -- exposed so any
 * consumer of this shared socket (e.g. the admin debug dashboard) can show
 * a visible "reconnecting" state instead of silently going stale while a
 * drop is being retried. 'reconnecting' specifically means "was open at
 * least once, then dropped" -- the very first connect attempt is
 * 'connecting', not 'reconnecting'.
 * @type {import('svelte/store').Writable<'connecting'|'open'|'reconnecting'|'closed'>}
 */
export const connectionState = writable('closed');

/** @typedef {{ onEvent: (type: string, data: any) => void, onResync?: () => void }} ChannelListener */

/** @type {Map<string, Set<ChannelListener>>} */
const channelListeners = new Map();
/** @type {Set<ChannelListener>} */
const userEventListeners = new Set();

/** @type {WebSocket | null} */
let socket = null;
let reconnectDelay = BASE_RECONNECT_DELAY_MS;
/** @type {ReturnType<typeof setTimeout> | null} */
let reconnectTimer = null;
// False only until the very first successful connect; after that, every
// fresh open() is a *re*connect and may have missed events, so it's the
// signal for whether to fire onResync callbacks.
let hasConnectedBefore = false;
let wantConnected = false;
/** @type {number | null} */
let currentUserId = null;

function realtimeWebSocketUrl() {
	if (typeof window === 'undefined') return '';
	const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	if (/^https?:\/\//.test(API_BASE_URL)) {
		const url = new URL(`${API_BASE_URL}/ws`);
		url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
		return url.toString();
	}
	return `${protocol}//${window.location.host}${API_BASE_URL}/ws`;
}

function userChannel() {
	return currentUserId == null ? null : `user:${currentUserId}`;
}

function clearReconnectTimer() {
	if (reconnectTimer) {
		clearTimeout(reconnectTimer);
		reconnectTimer = null;
	}
}

function scheduleReconnect() {
	if (!wantConnected || reconnectTimer) return;
	reconnectTimer = setTimeout(() => {
		reconnectTimer = null;
		connect();
	}, reconnectDelay);
	reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
}

/** @param {'subscribe'|'unsubscribe'} action @param {string} channel */
function sendFrame(action, channel) {
	if (socket && socket.readyState === WebSocket.OPEN) {
		socket.send(JSON.stringify({ action, channel }));
	}
}

/** Re-subscribes every locally-active channel and, on a *re*connect only,
 * tells every listener to refetch via REST in case it missed something
 * while the socket was down. */
function flushAfterConnect() {
	const isReconnect = hasConnectedBefore;
	hasConnectedBefore = true;
	for (const [channel, listeners] of channelListeners) {
		sendFrame('subscribe', channel);
		if (isReconnect) for (const listener of listeners) listener.onResync?.();
	}
	if (isReconnect) for (const listener of userEventListeners) listener.onResync?.();
}

/** @param {string} raw @returns {{ channel?: string, type?: string, data?: any } | null} */
function parseEnvelope(raw) {
	try {
		return JSON.parse(raw);
	} catch {
		return null;
	}
}

/** @param {MessageEvent} event */
function handleMessage(event) {
	const envelope = parseEnvelope(event.data);
	if (!envelope || typeof envelope !== 'object' || envelope.type === 'error') return;
	const { channel, type, data } = envelope;
	if (!channel || !type) return;

	if (channel === userChannel()) {
		for (const listener of userEventListeners) listener.onEvent(type, data);
	}
	const listeners = channelListeners.get(channel);
	if (listeners) for (const listener of listeners) listener.onEvent(type, data);
}

function connect() {
	clearReconnectTimer();
	if (!wantConnected || typeof window === 'undefined') return;
	if (
		socket &&
		(socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)
	) {
		return;
	}
	const url = realtimeWebSocketUrl();
	if (!url) return;
	connectionState.set(hasConnectedBefore ? 'reconnecting' : 'connecting');
	try {
		const nextSocket = new WebSocket(url);
		socket = nextSocket;
		nextSocket.onopen = () => {
			reconnectDelay = BASE_RECONNECT_DELAY_MS;
			connectionState.set('open');
			flushAfterConnect();
		};
		nextSocket.onmessage = handleMessage;
		nextSocket.onclose = () => {
			if (socket === nextSocket) socket = null;
			if (wantConnected) {
				connectionState.set('reconnecting');
				scheduleReconnect();
			}
		};
		nextSocket.onerror = () => {
			nextSocket.close();
		};
	} catch {
		connectionState.set('reconnecting');
		scheduleReconnect();
	}
}

function disconnect() {
	wantConnected = false;
	clearReconnectTimer();
	hasConnectedBefore = false;
	reconnectDelay = BASE_RECONNECT_DELAY_MS;
	connectionState.set('closed');
	if (socket) {
		const current = socket;
		socket = null;
		current.onclose = null;
		current.close();
	}
}

if (typeof window !== 'undefined') {
	authStore.subscribe((state) => {
		const nextUserId = state.status === 'authenticated' ? (state.user?.id ?? null) : null;
		if (nextUserId == null) {
			currentUserId = null;
			if (wantConnected) disconnect();
			return;
		}
		if (wantConnected && currentUserId === nextUserId) return;
		currentUserId = nextUserId;
		if (wantConnected) disconnect();
		wantConnected = true;
		connect();
	});
}

/**
 * Subscribe to a channel ("post:42", "feed:discussion", "conversation:7:19").
 * Safe to call before the socket is open -- the subscription is queued and
 * flushed on connect. `onResync` is optional and fires once after a
 * *re*connect (never the first connect) so the caller can refetch via REST
 * to catch up on anything missed while disconnected.
 *
 * @param {string} channel
 * @param {(type: string, data: any) => void} onEvent
 * @param {{ onResync?: () => void }} [options]
 * @returns {() => void} unsubscribe
 */
export function subscribe(channel, onEvent, { onResync } = {}) {
	/** @type {ChannelListener} */
	const listener = { onEvent, onResync };
	let listeners = channelListeners.get(channel);
	if (!listeners) {
		listeners = new Set();
		channelListeners.set(channel, listeners);
	}
	listeners.add(listener);
	sendFrame('subscribe', channel);
	return () => {
		const current = channelListeners.get(channel);
		if (!current) return;
		current.delete(listener);
		if (current.size === 0) {
			channelListeners.delete(channel);
			sendFrame('unsubscribe', channel);
		}
	};
}

/**
 * Always-on notifications for the signed-in user's own "user:{id}" channel.
 * No channel name to pass -- the server already auto-subscribes every
 * connection to it on accept, so this just registers a local listener.
 *
 * @param {(type: string, data: any) => void} onEvent
 * @param {{ onResync?: () => void }} [options]
 * @returns {() => void} unsubscribe
 */
export function onUserEvent(onEvent, { onResync } = {}) {
	/** @type {ChannelListener} */
	const listener = { onEvent, onResync };
	userEventListeners.add(listener);
	return () => userEventListeners.delete(listener);
}
