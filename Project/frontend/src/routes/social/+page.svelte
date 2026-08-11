<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onDestroy } from 'svelte';

	import AttachmentUploader from '$lib/components/AttachmentUploader.svelte';
	import AttachmentMedia from '$lib/components/AttachmentMedia.svelte';
	import {
		getConversation,
		getNotifications,
		markNotificationRead,
		notificationWebSocketUrl,
		normalizeNotification,
		sendDirectMessage
	} from '$lib/services/messagingApi.js';
	import { authStore } from '$lib/stores/authStore.js';
	import { deleteAttachment } from '$lib/services/uploadApi.js';

	let loaded = $state(false);
	let loading = $state(false);
	let error = $state('');
	let recipient = $state('');
	let loadedRecipient = $state('');
	let body = $state('');
	let sending = $state(false);
	let conversationLoading = $state(false);
	let messages = $state(/** @type {Record<string, any>[]} */ ([]));
	let notifications = $state(/** @type {Record<string, any>[]} */ ([]));
	let messageAttachments = $state(/** @type {Record<string, any>[]} */ ([]));
	const controller = new AbortController();
	/** @type {WebSocket | null} */
	let socket = null;
	/** @type {ReturnType<typeof setTimeout> | null} */
	let reconnectTimer = null;
	let reconnectAttempt = 0;
	let disposed = false;

	$effect(() => {
		if ($authStore.status === 'guest') {
			void goto(resolve('/login'));
		} else if ($authStore.status === 'authenticated' && !loaded) {
			loaded = true;
			void loadNotifications();
			connectNotifications();
		}
	});

	$effect(() => {
		if (recipient.trim() !== loadedRecipient) messages = [];
	});

	onDestroy(() => {
		disposed = true;
		controller.abort();
		if (reconnectTimer) clearTimeout(reconnectTimer);
		socket?.close();
		for (const attachment of messageAttachments) {
			void deleteAttachment(Number(attachment.id)).catch(() => {});
		}
	});

	async function loadNotifications() {
		loading = true;
		error = '';
		try {
			const result = await getNotifications({ signal: controller.signal });
			notifications = Array.isArray(result) ? result : [];
		} catch (requestError) {
			if (!controller.signal.aborted) {
				error =
					requestError instanceof Error ? requestError.message : 'Could not load notifications.';
			}
		} finally {
			loading = false;
		}
	}

	function connectNotifications() {
		const url = notificationWebSocketUrl();
		if (!url || socket || disposed) return;
		try {
			socket = new WebSocket(url);
		} catch {
			scheduleReconnect();
			return;
		}
		socket.onopen = () => {
			reconnectAttempt = 0;
			void syncLoadedConversation();
		};
		socket.onmessage = (event) => {
			try {
				const incoming = normalizeNotification(JSON.parse(String(event.data)));
				notifications = [incoming, ...notifications.filter((item) => item.id !== incoming.id)];
				appendIncomingMessage(incoming.direct_message);
			} catch {
				// Ignore malformed push data; the durable list remains available.
			}
		};
		socket.onclose = () => {
			socket = null;
			scheduleReconnect();
		};
	}

	/** @param {Record<string, any> | null | undefined} message */
	function appendIncomingMessage(message) {
		if (!message || !loadedRecipient) return;
		const currentUsername = String($authStore.user?.username || '').toLowerCase();
		const sender = String(message.sender_username || '').toLowerCase();
		const recipientUsername = String(message.recipient_username || '').toLowerCase();
		const otherParticipant = sender === currentUsername ? recipientUsername : sender;
		if (otherParticipant !== loadedRecipient.toLowerCase()) return;
		if (messages.some((item) => Number(item.id) === Number(message.id))) return;
		messages = [...messages, message].sort((left, right) => Number(left.id) - Number(right.id));
	}

	async function syncLoadedConversation() {
		const username = loadedRecipient;
		if (!username || controller.signal.aborted) return;
		try {
			const result = await getConversation(username, { signal: controller.signal });
			if (loadedRecipient.toLowerCase() === username.toLowerCase()) messages = result;
		} catch {
			// Reconnect synchronization is best effort; the socket remains usable.
		}
	}

	function scheduleReconnect() {
		if (disposed || reconnectTimer) return;
		const delay = Math.min(30_000, 1_000 * 2 ** reconnectAttempt);
		reconnectAttempt += 1;
		reconnectTimer = setTimeout(() => {
			reconnectTimer = null;
			connectNotifications();
		}, delay);
	}

	async function loadConversation() {
		const username = recipient.trim();
		if (!username || conversationLoading) return;
		conversationLoading = true;
		error = '';
		try {
			const result = await getConversation(username, { signal: controller.signal });
			messages = Array.isArray(result) ? result : [];
			loadedRecipient = username;
		} catch (requestError) {
			messages = [];
			loadedRecipient = '';
			error =
				requestError instanceof Error ? requestError.message : 'Could not load the conversation.';
		} finally {
			conversationLoading = false;
		}
	}

	/** @param {SubmitEvent} event */
	async function handleSend(event) {
		event.preventDefault();
		const username = recipient.trim();
		const messageBody = body.trim();
		if (!username || !messageBody || sending) return;
		sending = true;
		error = '';
		try {
			const message = /** @type {Record<string, any>} */ (
				await sendDirectMessage({
					recipientUsername: username,
					body: messageBody,
					attachmentIds: messageAttachments.map((item) => Number(item.id))
				})
			);
			messages = [...messages, message];
			loadedRecipient = username;
			body = '';
			messageAttachments = [];
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not send the message.';
		} finally {
			sending = false;
		}
	}

	/** @param {Record<string, any>} attachment */
	async function removeMessageAttachment(attachment) {
		try {
			await deleteAttachment(Number(attachment.id));
			messageAttachments = messageAttachments.filter((item) => item.id !== attachment.id);
		} catch (requestError) {
			error =
				requestError instanceof Error ? requestError.message : 'Could not remove the attachment.';
		}
	}

	/** @param {Record<string, any>} notification */
	async function markRead(notification) {
		if (notification.is_read) return;
		try {
			const updated = /** @type {Record<string, any>} */ (
				await markNotificationRead(Number(notification.id))
			);
			notifications = notifications.map((item) => (item.id === notification.id ? updated : item));
		} catch (requestError) {
			error =
				requestError instanceof Error ? requestError.message : 'Could not mark the notification.';
		}
	}
</script>

<svelte:head><title>Messages and notifications | Zonix</title></svelte:head>

<main class="social-page">
	<header>
		<p class="eyebrow">Social</p>
		<h1>Messages and notifications</h1>
	</header>

	{#if error}<div class="error" role="alert">{error}</div>{/if}

	<div class="columns">
		<section class="panel card" aria-labelledby="messages-heading">
			<h2 id="messages-heading">Direct messages</h2>
			<label for="recipient">Conversation with</label>
			<div class="recipient-row">
				<input
					id="recipient"
					bind:value={recipient}
					autocomplete="username"
					placeholder="Username"
				/>
				<button
					type="button"
					disabled={!recipient.trim() || conversationLoading}
					onclick={loadConversation}
				>
					{conversationLoading ? 'Loading…' : 'Load history'}
				</button>
			</div>

			<div class="messages" aria-live="polite">
				{#each messages as message (message.id)}
					<article class:mine={message.sender_username === $authStore.user?.username}>
						<strong>{message.sender_username}</strong>
						<span>{message.body}</span>
						{#each message.attachments || [] as attachment (attachment.id)}
							<AttachmentMedia {attachment} />
						{/each}
					</article>
				{:else}
					<p class="muted">Load a username to view your conversation.</p>
				{/each}
			</div>

			<form class="message-form" onsubmit={handleSend}>
				<label for="message-body">Message</label>
				<textarea id="message-body" bind:value={body} maxlength="4000" required disabled={sending}
				></textarea>
				<AttachmentUploader
					disabled={sending || messageAttachments.length >= 4}
					onUploaded={(attachment) => (messageAttachments = [...messageAttachments, attachment])}
				/>
				{#if messageAttachments.length}
					<ul class="staged-attachments">
						{#each messageAttachments as attachment (attachment.id)}
							<li>
								<span>{attachment.filename}</span>
								<button
									type="button"
									disabled={sending}
									onclick={() => removeMessageAttachment(attachment)}>Remove</button
								>
							</li>
						{/each}
					</ul>
				{/if}
				<button
					class="primary-button"
					type="submit"
					disabled={sending || !recipient.trim() || !body.trim()}
					>{sending ? 'Sending…' : 'Send message'}</button
				>
			</form>
		</section>

		<section class="panel card" aria-labelledby="notifications-heading">
			<div class="section-heading">
				<h2 id="notifications-heading">Notifications</h2>
				<button type="button" onclick={loadNotifications}>Refresh</button>
			</div>
			{#if loading}
				<p role="status">Loading notifications…</p>
			{:else}
				<ul class="notifications">
					{#each notifications as notification (notification.id)}
						<li class:unread={!notification.is_read}>
							<span>{notification.message}</span>
							{#if !notification.is_read}<button
									type="button"
									onclick={() => markRead(notification)}>Mark read</button
								>{/if}
						</li>
					{:else}
						<li>No notifications yet.</li>
					{/each}
				</ul>
			{/if}
		</section>
	</div>
</main>

<style>
	.social-page {
		max-width: 1200px;
		margin: 0 auto;
		padding: 48px 0 80px;
	}
	.eyebrow {
		margin: 0;
		color: var(--accent-2);
		font-weight: 900;
		letter-spacing: 0.14em;
		text-transform: uppercase;
	}
	h1 {
		margin: 8px 0 28px;
		font-size: clamp(38px, 6vw, 62px);
		letter-spacing: -0.05em;
	}
	.columns {
		display: grid;
		grid-template-columns: 1.4fr 1fr;
		gap: 20px;
	}
	.panel {
		display: grid;
		align-content: start;
		gap: 12px;
		padding: 22px;
	}
	.panel > * {
		position: relative;
		z-index: 1;
	}
	h2 {
		margin: 0;
	}
	label {
		color: var(--text-soft);
		font-weight: 900;
	}
	input,
	textarea {
		width: 100%;
		border: 1px solid var(--border-soft);
		border-radius: 12px;
		padding: 11px;
		background: #050b16;
		color: var(--text-main);
	}
	textarea {
		min-height: 100px;
		resize: vertical;
	}
	.recipient-row {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 8px;
	}
	.recipient-row button,
	.section-heading button,
	.notifications button {
		border: 1px solid var(--border-soft);
		border-radius: 999px;
		padding: 8px 12px;
		background: transparent;
		color: var(--text-main);
		font-weight: 800;
	}
	.messages {
		display: grid;
		gap: 8px;
		max-height: 340px;
		overflow-y: auto;
		padding: 10px;
		border: 1px solid var(--border-muted);
		border-radius: 12px;
	}
	.messages article {
		display: grid;
		justify-self: start;
		gap: 4px;
		max-width: 85%;
		padding: 10px;
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.045);
		color: var(--text-soft);
	}
	.messages article.mine {
		justify-self: end;
		background: rgba(59, 130, 246, 0.18);
	}
	.message-form {
		display: grid;
		gap: 8px;
	}
	.message-form button {
		justify-self: start;
	}
	.staged-attachments {
		display: grid;
		gap: 5px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.staged-attachments li {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		color: var(--text-soft);
		font-size: 13px;
	}
	.staged-attachments button {
		border: 0;
		background: transparent;
		color: var(--danger);
	}
	.section-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.notifications {
		display: grid;
		gap: 8px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.notifications li {
		display: grid;
		gap: 8px;
		padding: 12px;
		border: 1px solid var(--border-muted);
		border-radius: 12px;
		color: var(--text-soft);
	}
	.notifications li.unread {
		border-color: var(--accent-2);
		background: rgba(59, 130, 246, 0.1);
	}
	.notifications button {
		justify-self: start;
	}
	.muted {
		color: var(--text-muted);
	}
	.error {
		margin-bottom: 16px;
		padding: 14px;
		border: 1px solid rgba(255, 107, 134, 0.45);
		border-radius: 12px;
		color: #ffb1bf;
	}
	@media (max-width: 850px) {
		.columns {
			grid-template-columns: 1fr;
		}
	}
</style>
