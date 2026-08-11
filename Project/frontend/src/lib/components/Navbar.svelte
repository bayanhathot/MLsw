<script>
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { onDestroy } from 'svelte';

	import zonixLogo from '../../assets/zonix-logo.svg';
	import {
		getConversations,
		getNotifications,
		markNotificationRead,
		notificationWebSocketUrl,
		normalizeNotification
	} from '$lib/services/messagingApi.js';
	import { authStore } from '$lib/stores/authStore.js';

	let menuOpen = $state(false);
	let isLoggingOut = $state(false);
	let logoutError = $state('');
	let notificationsOpen = $state(false);
	/** @type {import('$lib/types.js').AppNotification[]} */
	let notifications = $state([]);
	let messageUnread = $state(0);
	let socialLoadedFor = $state('');
	/** @type {WebSocket | null} */
	let socket = null;

	let unreadNotifications = $derived(notifications.filter((item) => !item.is_read).length);

	$effect(() => {
		const username = $authStore.user?.username || '';
		if ($authStore.status === 'authenticated' && username && socialLoadedFor !== username) {
			socialLoadedFor = username;
			void loadSocialIndicators();
			connectSocket();
		}
		if ($authStore.status !== 'authenticated' && socialLoadedFor) {
			socialLoadedFor = '';
			notifications = [];
			messageUnread = 0;
			closeSocket();
		}
	});

	onDestroy(closeSocket);

	/** @param {string} path */
	function isCurrent(path) {
		return path === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(path);
	}

	async function loadSocialIndicators() {
		try {
			const [notificationRows, conversations] = await Promise.all([
				getNotifications(),
				getConversations()
			]);
			notifications = notificationRows;
			messageUnread = conversations.reduce((sum, item) => sum + item.unreadCount, 0);
		} catch {
			// Best-effort realtime/indicator behavior; REST state remains authoritative.
		}
	}

	function closeSocket() {
		if (socket) {
			socket.close();
			socket = null;
		}
	}

	function connectSocket() {
		closeSocket();
		const url = notificationWebSocketUrl();
		if (!url) return;
		try {
			socket = new WebSocket(url);
			socket.onmessage = (/** @type {MessageEvent} */ event) => {
				try {
					const item = normalizeNotification(JSON.parse(event.data));
					notifications = [item, ...notifications.filter((existing) => existing.id !== item.id)];
					if (item.kind === 'direct_message') messageUnread += 1;
				} catch {
					// Best-effort realtime/indicator behavior; REST state remains authoritative.
				}
			};
			socket.onopen = () => socket?.send('ready');
		} catch {
			// Best-effort realtime/indicator behavior; REST state remains authoritative.
		}
	}

	/** @param {import('$lib/types.js').AppNotification} item */
	function notificationHref(item) {
		if (item.kind === 'direct_message') return '/messages';
		if (item.kind === 'friend_request' || item.kind === 'friend_accepted')
			return '/community?tab=people';
		if (item.entity_type === 'post') return '/community';
		if (item.entity_type === 'user') return '/community?tab=people';
		return '/community';
	}

	/** @param {import('$lib/types.js').AppNotification} item */
	async function openNotification(item) {
		if (!item.is_read) {
			try {
				const updated = await markNotificationRead(item.id);
				notifications = notifications.map((row) =>
					row.id === item.id ? { ...row, is_read: updated.is_read } : row
				);
			} catch {
				// Best-effort realtime/indicator behavior; REST state remains authoritative.
			}
		}
		notificationsOpen = false;
		menuOpen = false;
	}

	async function handleLogout() {
		if (isLoggingOut) return;
		isLoggingOut = true;
		logoutError = '';
		try {
			await authStore.logout();
			menuOpen = false;
		} catch (error) {
			logoutError = error instanceof Error ? error.message : 'Could not sign out.';
		} finally {
			isLoggingOut = false;
		}
	}
</script>

<nav class="navbar" aria-label="Main navigation">
	<a class="logo" href={resolve('/')} aria-label="Zonix DJ" onclick={() => (menuOpen = false)}
		><img src={zonixLogo} alt="Zonix" /></a
	>
	<button
		class="menu-toggle"
		type="button"
		aria-label="Toggle menu"
		aria-expanded={menuOpen}
		onclick={() => (menuOpen = !menuOpen)}>{menuOpen ? '×' : '☰'}</button
	>

	<div class:open={menuOpen} class="links">
		<div class="navigation">
			<a
				class:active={isCurrent('/')}
				class="nav-link"
				href={resolve('/')}
				onclick={() => (menuOpen = false)}>DJ</a
			>
			<a
				class:active={isCurrent('/feed')}
				class="nav-link"
				href={resolve('/feed')}
				onclick={() => (menuOpen = false)}>Discover</a
			>
			<a
				class:active={isCurrent('/community') || isCurrent('/forum')}
				class="nav-link"
				href={resolve('/community')}
				onclick={() => (menuOpen = false)}>Community</a
			>
			{#if $authStore.status === 'authenticated'}<a
					class:active={isCurrent('/library')}
					class="nav-link"
					href={resolve('/library')}
					onclick={() => (menuOpen = false)}>Library</a
				>{/if}
		</div>

		<div class="account">
			{#if $authStore.status === 'authenticated' && $authStore.user}
				<a
					class="icon-button"
					href={resolve('/community?tab=people')}
					aria-label="Search people"
					title="Find people">⌕</a
				>
				<div class="notification-wrap">
					<button
						class="icon-button"
						type="button"
						aria-label="Notifications"
						aria-expanded={notificationsOpen}
						onclick={() => {
							notificationsOpen = !notificationsOpen;
							if (notificationsOpen) void loadSocialIndicators();
						}}
						>♢{#if unreadNotifications}<b>{unreadNotifications > 9 ? '9+' : unreadNotifications}</b
							>{/if}</button
					>
					{#if notificationsOpen}<div class="notification-panel">
							<div class="panel-heading">
								<strong>Notifications</strong><span>{unreadNotifications} new</span>
							</div>
							{#each notifications.slice(0, 8) as item (item.id)}<a
									class:unread={!item.is_read}
									href={resolve(notificationHref(item))}
									onclick={() => openNotification(item)}
									><span>{item.message}</span><small
										>{new Date(item.created_at).toLocaleDateString()}</small
									></a
								>{:else}<p>No notifications yet.</p>{/each}
						</div>{/if}
				</div>
				<a class="icon-button" href={resolve('/messages')} aria-label="Messages" title="Messages"
					>✉{#if messageUnread}<b>{messageUnread > 9 ? '9+' : messageUnread}</b>{/if}</a
				>
				<a class="avatar-link" href={resolve('/profile')} aria-label="Your profile"
					>{$authStore.user.username.slice(0, 2).toUpperCase()}</a
				>
				<button class="signout" type="button" disabled={isLoggingOut} onclick={handleLogout}
					>{isLoggingOut ? '…' : 'Sign out'}</button
				>
			{:else if $authStore.status === 'checking'}<span class="user-chip">Checking…</span>
			{:else}<a class="signin" href={resolve('/login')}>Sign in</a>{/if}
		</div>
		{#if logoutError}<p class="logout-error" role="alert">{logoutError}</p>{/if}
	</div>
</nav>

<style>
	.navbar {
		position: relative;
		z-index: 80;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 22px;
		padding: 18px 0 12px;
	}
	.logo {
		display: inline-flex;
		width: 165px;
	}
	.logo img {
		width: 100%;
	}
	.links,
	.navigation,
	.account {
		display: flex;
		align-items: center;
	}
	.links {
		gap: 16px;
		margin-left: auto;
	}
	.navigation {
		gap: 3px;
	}
	.account {
		gap: 7px;
	}
	.nav-link {
		border-radius: 999px;
		padding: 9px 12px;
		color: #8ea1bb;
		font-size: 13px;
		font-weight: 900;
		text-decoration: none;
	}
	.nav-link:hover,
	.nav-link.active {
		background: rgba(74, 116, 226, 0.13);
		color: white;
	}
	.icon-button,
	.avatar-link {
		position: relative;
		display: grid;
		width: 40px;
		height: 40px;
		place-items: center;
		border: 1px solid rgba(125, 183, 255, 0.14);
		border-radius: 13px;
		background: rgba(125, 183, 255, 0.04);
		color: #bfd6f5;
		font-weight: 900;
		text-decoration: none;
	}
	.icon-button b {
		position: absolute;
		top: -5px;
		right: -5px;
		display: grid;
		min-width: 18px;
		height: 18px;
		place-items: center;
		border: 2px solid #07101f;
		border-radius: 999px;
		background: #695fff;
		color: white;
		font-size: 9px;
	}
	.avatar-link {
		border-color: rgba(127, 156, 255, 0.32);
		background: linear-gradient(135deg, #315fb7, #725bd7);
		color: white;
		font-size: 10px;
	}
	.signout,
	.signin {
		border: 1px solid rgba(125, 183, 255, 0.13);
		border-radius: 999px;
		padding: 9px 11px;
		background: transparent;
		color: #8ea1bb;
		font-size: 11px;
		font-weight: 900;
		text-decoration: none;
	}
	.notification-wrap {
		position: relative;
	}
	.notification-panel {
		position: absolute;
		top: 48px;
		right: 0;
		width: min(360px, calc(100vw - 32px));
		overflow: hidden;
		border: 1px solid rgba(125, 183, 255, 0.17);
		border-radius: 20px;
		background: #07101f;
		box-shadow: 0 24px 70px rgba(0, 0, 0, 0.48);
	}
	.panel-heading {
		display: flex;
		justify-content: space-between;
		padding: 14px 16px;
		border-bottom: 1px solid rgba(125, 183, 255, 0.1);
	}
	.panel-heading span {
		color: #6f839e;
		font-size: 11px;
	}
	.notification-panel > a {
		display: grid;
		gap: 3px;
		padding: 12px 16px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.035);
		color: #a6bad5;
		font-size: 12px;
		text-decoration: none;
	}
	.notification-panel > a.unread {
		background: rgba(82, 112, 255, 0.08);
		color: #e2edff;
	}
	.notification-panel small {
		color: #62748d;
	}
	.notification-panel p {
		padding: 16px;
		color: #7589a4;
	}
	.menu-toggle {
		display: none;
		width: 42px;
		height: 42px;
		border: 1px solid rgba(125, 183, 255, 0.14);
		border-radius: 13px;
		background: rgba(125, 183, 255, 0.05);
		color: white;
	}
	.logout-error {
		margin: 0;
		color: #ffb1bf;
		font-size: 11px;
	}
	.user-chip {
		color: #7e91aa;
		font-size: 12px;
	}
	@media (max-width: 820px) {
		.menu-toggle {
			display: grid;
			place-items: center;
		}
		.links {
			position: absolute;
			top: 68px;
			right: 0;
			left: 0;
			display: none;
			align-items: stretch;
			padding: 14px;
			border: 1px solid rgba(125, 183, 255, 0.15);
			border-radius: 20px;
			background: #07101f;
			box-shadow: 0 24px 70px rgba(0, 0, 0, 0.48);
		}
		.links.open {
			display: grid;
		}
		.navigation {
			display: grid;
			grid-template-columns: repeat(2, 1fr);
		}
		.account {
			justify-content: center;
			padding-top: 10px;
			border-top: 1px solid rgba(125, 183, 255, 0.08);
		}
		.notification-panel {
			position: fixed;
			top: 80px;
			right: 16px;
		}
		.nav-link {
			text-align: center;
		}
		.signout {
			display: none;
		}
	}
	@media (max-width: 480px) {
		.logo {
			width: 145px;
		}
	}
</style>
