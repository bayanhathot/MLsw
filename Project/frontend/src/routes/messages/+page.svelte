<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { onDestroy } from 'svelte';

	import AttachmentMedia from '$lib/components/AttachmentMedia.svelte';
	import AttachmentUploader from '$lib/components/AttachmentUploader.svelte';
	import {
		getConversation,
		getConversations,
		notificationWebSocketUrl,
		normalizeNotification,
		sendDirectMessage
	} from '$lib/services/messagingApi.js';
	import { deleteAttachment } from '$lib/services/uploadApi.js';
	import { authStore } from '$lib/stores/authStore.js';

	/** @type {import('$lib/types.js').Conversation[]} */
	let conversations = $state([]);
	let activeUsername = $state('');
	/** @type {import('$lib/types.js').DirectMessage[]} */
	let messages = $state([]);
	let loading = $state(true);
	let loadingThread = $state(false);
	let error = $state('');
	let body = $state('');
	let sending = $state(false);
	/** @type {Record<string, any>[]} */
	let attachments = $state([]);
	let inboxLoadedFor = $state('');
	/** @type {WebSocket | null} */
	let socket = null;

	$effect(() => {
		if ($authStore.status === 'guest') {
			void goto(resolve('/login'));
			return;
		}
		const username = $authStore.user?.username || '';
		if ($authStore.status === 'authenticated' && username && inboxLoadedFor !== username) {
			inboxLoadedFor = username;
			void loadInbox();
			connectSocket();
		}
	});

	onDestroy(() => {
		if (socket) socket.close();
	});

	function connectSocket() {
		if (socket) socket.close();
		const url = notificationWebSocketUrl();
		if (!url) return;
		try {
			socket = new WebSocket(url);
			socket.onopen = () => socket?.send('ready');
			socket.onmessage = (/** @type {MessageEvent} */ event) => {
				try {
					const notification = normalizeNotification(JSON.parse(event.data));
					const incoming = notification.direct_message;
					if (!incoming) return;
					if (incoming.sender_username === activeUsername) {
						if (!messages.some((item) => item.id === incoming.id))
							messages = [...messages, incoming];
						void getConversation(activeUsername)
							.then((rows) => {
								messages = rows;
							})
							.catch(() => {});
					} else {
						const existing = conversations.find(
							(item) => item.username === incoming.sender_username
						);
						conversations = [
							{
								username: incoming.sender_username,
								displayName: existing?.displayName || incoming.sender_username,
								avatarUrl: existing?.avatarUrl || null,
								lastMessage: incoming.body,
								lastMessageAt: incoming.created_at,
								unreadCount: (existing?.unreadCount || 0) + 1
							},
							...conversations.filter((item) => item.username !== incoming.sender_username)
						];
					}
				} catch {
					// Best-effort realtime/indicator behavior; REST state remains authoritative.
				}
			};
		} catch {
			// Best-effort realtime/indicator behavior; REST state remains authoritative.
		}
	}

	async function loadInbox() {
		loading = true;
		error = '';
		try {
			conversations = await getConversations();
			const requested = page.url.searchParams.get('with') || '';
			const first = requested || conversations[0]?.username || '';
			if (first) await openConversation(first);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not load messages.';
		} finally {
			loading = false;
		}
	}

	/** @param {string} username */
	async function openConversation(username) {
		if (!username) return;
		activeUsername = username;
		loadingThread = true;
		error = '';
		try {
			messages = await getConversation(username);
			conversations = conversations.map((item) =>
				item.username === username ? { ...item, unreadCount: 0 } : item
			);
			await goto(resolve(`/messages?with=${encodeURIComponent(username)}`), {
				replaceState: true,
				noScroll: true
			});
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not load conversation.';
		} finally {
			loadingThread = false;
		}
	}

	/** @param {SubmitEvent} event */
	async function send(event) {
		event.preventDefault();
		if (!activeUsername || !body.trim() || sending) return;
		sending = true;
		error = '';
		try {
			const message = await sendDirectMessage({
				recipientUsername: activeUsername,
				body: body.trim(),
				attachmentIds: attachments.map((item) => Number(item.id))
			});
			messages = [...messages, message];
			body = '';
			attachments = [];
			conversations = [
				{
					username: activeUsername,
					displayName: activeUsername,
					avatarUrl: null,
					lastMessage: message.body,
					lastMessageAt: message.created_at,
					unreadCount: 0
				},
				...conversations.filter((item) => item.username !== activeUsername)
			];
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not send message.';
		} finally {
			sending = false;
		}
	}

	/** @param {Record<string, any>} item */
	async function removeAttachment(item) {
		try {
			await deleteAttachment(Number(item.id));
			attachments = attachments.filter((a) => a.id !== item.id);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not remove attachment.';
		}
	}

	/** @param {string} value */
	function labelTime(value) {
		const date = new Date(value);
		return Number.isNaN(date.getTime())
			? ''
			: date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}
</script>

<svelte:head><title>Messages | Zonix</title></svelte:head>

<main class="messages-page">
	<header>
		<p class="eyebrow">Your conversations</p>
		<h1>Messages</h1>
		<p>Private conversations between friends, without leaving the music.</p>
	</header>
	{#if error}<div class="error" role="alert">{error}</div>{/if}
	<section class="inbox-shell">
		<aside class="conversation-list">
			<div class="list-heading">
				<strong>Conversations</strong><a href={resolve('/community?tab=people')}>Find friends</a>
			</div>
			{#if loading}<p class="muted">Loading…</p>
			{:else if conversations.length === 0}<div class="empty">
					<strong>No conversations yet</strong>
					<p>Add friends from Community, then message them from their profile.</p>
				</div>
			{:else}{#each conversations as conversation (conversation.username)}<button
						class:active={activeUsername === conversation.username}
						type="button"
						onclick={() => openConversation(conversation.username)}
					>
						<div class="avatar">
							{conversation.avatarUrl
								? ''
								: conversation.username.slice(0, 2).toUpperCase()}{#if conversation.avatarUrl}<img
									src={conversation.avatarUrl}
									alt=""
								/>{/if}
						</div>
						<div class="conversation-copy">
							<strong>{conversation.displayName || conversation.username}</strong><span
								>{conversation.lastMessage}</span
							>
						</div>
						{#if conversation.unreadCount}<b>{conversation.unreadCount}</b>{/if}
					</button>{/each}{/if}
		</aside>
		<div class="thread">
			{#if activeUsername}
				<div class="thread-heading">
					<div><strong>@{activeUsername}</strong><span>Friend conversation</span></div>
					<a href={resolve(`/users/${encodeURIComponent(activeUsername)}`)}>View profile</a>
				</div>
				<div class="message-list">
					{#if loadingThread}<p class="muted">Loading conversation…</p>
					{:else}{#each messages as message (message.id)}<article
								class:mine={message.sender_username === $authStore.user?.username}
							>
								<div>
									{#if message.body}<p>
											{message.body}
										</p>{/if}{#each message.attachments as attachment (attachment.id)}<AttachmentMedia
											{attachment}
										/>{/each}<time>{labelTime(message.created_at)}</time>
								</div>
							</article>{/each}{/if}
				</div>
				<form class="message-composer" onsubmit={send}>
					<textarea bind:value={body} maxlength="4000" placeholder="Write a message…" required
					></textarea>
					<div class="composer-row">
						<AttachmentUploader
							disabled={sending || attachments.length >= 4}
							onUploaded={(item) => (attachments = [...attachments, item])}
						/><button type="submit" disabled={sending || !body.trim()}
							>{sending ? 'Sending…' : 'Send'}</button
						>
					</div>
					{#if attachments.length}<div class="staged">
							{#each attachments as item (item.id)}<span
									>{item.filename}<button type="button" onclick={() => removeAttachment(item)}
										>×</button
									></span
								>{/each}
						</div>{/if}
				</form>
			{:else}<div class="thread-empty">
					<div>💬</div>
					<strong>Choose a conversation</strong>
					<p>Your friend conversations will stay together here.</p>
				</div>{/if}
		</div>
	</section>
</main>

<style>
	.messages-page {
		width: min(1180px, 100%);
		margin: 0 auto;
		padding: 42px 0 100px;
	}
	.eyebrow {
		margin: 0 0 5px;
		color: #7998c4;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.15em;
		text-transform: uppercase;
	}
	h1 {
		margin: 0;
		font-size: clamp(40px, 6vw, 64px);
		letter-spacing: -0.05em;
	}
	header > p:last-child {
		color: #8396af;
	}
	.error {
		margin: 16px 0;
		padding: 14px;
		border: 1px solid rgba(255, 107, 134, 0.35);
		border-radius: 15px;
		color: #ffb1bf;
	}
	.inbox-shell {
		display: grid;
		grid-template-columns: 330px minmax(0, 1fr);
		min-height: 650px;
		margin-top: 26px;
		overflow: hidden;
		border: 1px solid rgba(125, 183, 255, 0.16);
		border-radius: 26px;
		background: rgba(5, 11, 22, 0.85);
	}
	.conversation-list {
		border-right: 1px solid rgba(125, 183, 255, 0.1);
		background: rgba(9, 18, 34, 0.65);
	}
	.list-heading,
	.thread-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 18px;
		border-bottom: 1px solid rgba(125, 183, 255, 0.1);
	}
	.list-heading a,
	.thread-heading a {
		color: #9fc9ff;
		font-size: 12px;
		font-weight: 900;
		text-decoration: none;
	}
	.conversation-list > button {
		display: grid;
		width: 100%;
		grid-template-columns: auto minmax(0, 1fr) auto;
		gap: 11px;
		align-items: center;
		border: 0;
		border-bottom: 1px solid rgba(255, 255, 255, 0.04);
		padding: 13px 14px;
		background: transparent;
		color: white;
		text-align: left;
	}
	.conversation-list > button:hover,
	.conversation-list > button.active {
		background: rgba(74, 115, 217, 0.12);
	}
	.avatar {
		display: grid;
		width: 44px;
		height: 44px;
		place-items: center;
		overflow: hidden;
		border-radius: 14px;
		background: linear-gradient(135deg, #315fb7, #715bd7);
		font-size: 11px;
		font-weight: 900;
	}
	.avatar img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.conversation-copy {
		display: grid;
		gap: 3px;
		min-width: 0;
	}
	.conversation-copy span {
		overflow: hidden;
		color: #71839c;
		font-size: 11px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.conversation-list b {
		display: grid;
		min-width: 22px;
		height: 22px;
		place-items: center;
		border-radius: 999px;
		background: #5d76ff;
		font-size: 11px;
	}
	.thread {
		display: grid;
		grid-template-rows: auto minmax(0, 1fr) auto;
		min-width: 0;
	}
	.thread-heading strong,
	.thread-heading span {
		display: block;
	}
	.thread-heading span {
		margin-top: 2px;
		color: #6f829b;
		font-size: 11px;
	}
	.message-list {
		display: flex;
		overflow: auto;
		flex-direction: column;
		gap: 9px;
		padding: 20px;
	}
	.message-list article {
		display: flex;
		justify-content: flex-start;
	}
	.message-list article.mine {
		justify-content: flex-end;
	}
	.message-list article > div {
		max-width: min(72%, 620px);
		padding: 10px 13px;
		border: 1px solid rgba(125, 183, 255, 0.12);
		border-radius: 16px 16px 16px 5px;
		background: rgba(125, 183, 255, 0.06);
	}
	.message-list article.mine > div {
		border-color: rgba(90, 116, 255, 0.22);
		border-radius: 16px 16px 5px 16px;
		background: linear-gradient(135deg, rgba(48, 94, 203, 0.34), rgba(105, 76, 204, 0.24));
	}
	.message-list p {
		margin: 0;
		white-space: pre-wrap;
	}
	.message-list time {
		display: block;
		margin-top: 5px;
		color: #6c7d94;
		font-size: 10px;
		text-align: right;
	}
	.message-composer {
		display: grid;
		gap: 9px;
		padding: 15px;
		border-top: 1px solid rgba(125, 183, 255, 0.1);
	}
	textarea {
		min-height: 74px;
		border: 1px solid rgba(125, 183, 255, 0.14);
		border-radius: 15px;
		padding: 12px;
		resize: vertical;
		background: #050b16;
		color: white;
	}
	.composer-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.composer-row > button {
		border: 0;
		border-radius: 999px;
		padding: 10px 19px;
		background: linear-gradient(135deg, #356fe7, #725bd8);
		color: white;
		font-weight: 900;
	}
	.staged {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.staged span {
		padding: 6px 9px;
		border-radius: 999px;
		background: rgba(125, 183, 255, 0.07);
		color: #9db5d3;
		font-size: 11px;
	}
	.staged span button {
		border: 0;
		background: none;
		color: #ff9bad;
	}
	.empty,
	.thread-empty,
	.muted {
		color: #74869f;
	}
	.empty {
		padding: 20px;
	}
	.thread-empty {
		display: grid;
		place-content: center;
		justify-items: center;
		text-align: center;
	}
	.thread-empty div {
		font-size: 36px;
	}
	.thread-empty strong {
		color: #e5f0ff;
		font-size: 20px;
	}
	.thread-empty p {
		max-width: 360px;
	}
	@media (max-width: 780px) {
		.inbox-shell {
			grid-template-columns: 1fr;
		}
		.conversation-list {
			max-height: 260px;
			overflow: auto;
			border-right: 0;
			border-bottom: 1px solid rgba(125, 183, 255, 0.1);
		}
		.thread {
			min-height: 560px;
		}
	}
</style>
