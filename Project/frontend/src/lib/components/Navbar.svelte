<script>
	import { resolve } from '$app/paths';
	import { page } from '$app/state';

	import zonixLogo from '../../assets/zonix-logo.svg';
	import { authStore } from '$lib/stores/authStore.js';

	let menuOpen = $state(false);
	let isLoggingOut = $state(false);
	let logoutError = $state('');

	/** @param {string} path */
	function isCurrent(path) {
		return path === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(path);
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
	<a class="logo" href={resolve('/')} aria-label="Zonix home" onclick={() => (menuOpen = false)}>
		<img src={zonixLogo} alt="Zonix" />
	</a>

	<button
		class="menu-toggle"
		type="button"
		aria-label={menuOpen ? 'Close navigation menu' : 'Open navigation menu'}
		aria-expanded={menuOpen}
		aria-controls="main-navigation-links"
		onclick={() => (menuOpen = !menuOpen)}
	>
		<span aria-hidden="true">{menuOpen ? '×' : '☰'}</span>
	</button>

	<div id="main-navigation-links" class:open={menuOpen} class="links">
		<div class="navigation">
			<a
				class:active={isCurrent('/')}
				class="nav-link"
				href={resolve('/')}
				aria-current={isCurrent('/') ? 'page' : undefined}
				onclick={() => (menuOpen = false)}>Home</a
			>
			<a
				class:active={isCurrent('/feed')}
				class="nav-link"
				href={resolve('/feed')}
				aria-current={isCurrent('/feed') ? 'page' : undefined}
				onclick={() => (menuOpen = false)}>Mixes</a
			>
			<a
				class:active={isCurrent('/forum')}
				class="nav-link"
				href={resolve('/forum')}
				aria-current={isCurrent('/forum') ? 'page' : undefined}
				onclick={() => (menuOpen = false)}>Forum</a
			>
			{#if $authStore.status === 'authenticated'}
				<a
					class:active={isCurrent('/library')}
					class="nav-link"
					href={resolve('/library')}
					aria-current={isCurrent('/library') ? 'page' : undefined}
					onclick={() => (menuOpen = false)}>Library</a
				>
				<a
					class:active={isCurrent('/profile')}
					class="nav-link"
					href={resolve('/profile')}
					aria-current={isCurrent('/profile') ? 'page' : undefined}
					onclick={() => (menuOpen = false)}>Profile</a
				>
				<a
					class:active={isCurrent('/social')}
					class="nav-link"
					href={resolve('/social')}
					aria-current={isCurrent('/social') ? 'page' : undefined}
					onclick={() => (menuOpen = false)}>Social</a
				>
			{/if}
		</div>

		<div class="account">
			{#if $authStore.status === 'authenticated' && $authStore.user}
				<span class="user-chip">{$authStore.user.username}</span>
				<button
					class="secondary-button"
					type="button"
					disabled={isLoggingOut}
					onclick={handleLogout}
				>
					{isLoggingOut ? 'Signing out…' : 'Sign out'}
				</button>
			{:else if $authStore.status === 'checking'}
				<span class="user-chip" role="status">Checking account…</span>
			{:else}
				<a class="secondary-button sign-in" href={resolve('/login')}>Sign in</a>
			{/if}
		</div>

		{#if logoutError}<p class="logout-error" role="alert">{logoutError}</p>{/if}
	</div>
</nav>

<style>
	.navbar {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 24px;
		padding: 20px 0 14px;
	}

	.logo {
		display: inline-flex;
		width: 190px;
		min-width: 0;
	}

	.logo img {
		display: block;
		width: 100%;
		height: auto;
	}

	.links,
	.navigation,
	.account {
		display: flex;
		align-items: center;
	}

	.links {
		gap: 18px;
		margin-left: auto;
	}

	.navigation {
		gap: 4px;
	}

	.account {
		gap: 10px;
	}

	.nav-link {
		border-radius: 999px;
		padding: 10px 12px;
		color: var(--text-soft);
		font-size: 14px;
		font-weight: 800;
		text-decoration: none;
	}

	.nav-link:hover,
	.nav-link.active {
		background: rgba(59, 130, 246, 0.16);
		color: white;
	}

	.user-chip {
		max-width: 180px;
		overflow: hidden;
		border: 1px solid var(--border-muted);
		border-radius: 999px;
		padding: 10px 14px;
		background: rgba(255, 255, 255, 0.035);
		color: var(--text-soft);
		font-size: 14px;
		font-weight: 800;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sign-in {
		text-decoration: none;
	}

	.menu-toggle {
		display: none;
		width: 44px;
		height: 44px;
		border: 1px solid var(--border-soft);
		border-radius: 12px;
		background: rgba(59, 130, 246, 0.1);
		color: white;
		font-size: 24px;
	}

	.logout-error {
		margin: 0;
		color: #ffb1bf;
		font-size: 13px;
	}

	@media (max-width: 760px) {
		.logo {
			width: 150px;
		}

		.menu-toggle {
			display: grid;
			place-items: center;
		}

		.links {
			position: absolute;
			top: calc(100% - 4px);
			right: 0;
			left: 0;
			z-index: 60;
			display: none;
			align-items: stretch;
			margin: 0;
			padding: 16px;
			border: 1px solid var(--border-soft);
			border-radius: var(--radius-md);
			background: #07101f;
			box-shadow: var(--shadow-soft);
		}

		.links.open,
		.navigation,
		.account {
			display: grid;
		}

		.navigation,
		.account {
			gap: 8px;
		}

		.nav-link,
		.sign-in,
		.account button,
		.user-chip {
			width: 100%;
			max-width: none;
			text-align: center;
		}
	}
</style>
