<!--
  File: src/routes/login/+page.svelte
  Purpose: Login page for the cookie-authenticated Zonix account.
  What it does:
  - Submits credentials to the backend and redirects after authentication.
-->

<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { authStore } from '$lib/stores/authStore.js';

	let email = $state('');
	let password = $state('');
	let error = $state('');
	let isSubmitting = $state(false);

	/**
	 * Convert unknown caught errors into a readable message.
	 *
	 * @param {unknown} err
	 * @param {string} fallback
	 */
	function getErrorMessage(err, fallback) {
		if (err instanceof Error) {
			return err.message;
		}

		return fallback;
	}

	/**
	 * @param {SubmitEvent} event
	 */
	async function handleLogin(event) {
		event.preventDefault();

		error = '';

		if (!email.trim() || !password.trim()) {
			error = 'Please enter both email and password.';
			return;
		}

		isSubmitting = true;

		try {
			await authStore.login({
				email: email.trim(),
				password
			});

			await goto(resolve('/'));
		} catch (err) {
			error = getErrorMessage(err, 'Login failed.');
		} finally {
			isSubmitting = false;
		}
	}
</script>

<section class="auth-page">
	<div class="auth-card card">
		<p class="eyebrow">Account</p>
		<h1>Sign in.</h1>
		<p class="muted">
			Access your persistent mixes, saved community picks, and personalized feedback.
		</p>

		<form onsubmit={handleLogin}>
			<label for="email">Email</label>
			<input
				id="email"
				bind:value={email}
				type="email"
				placeholder="you@example.com"
				autocomplete="email"
				required
				disabled={isSubmitting}
			/>

			<label for="password">Password</label>
			<input
				id="password"
				bind:value={password}
				type="password"
				placeholder="Your password"
				autocomplete="current-password"
				required
				maxlength="72"
				disabled={isSubmitting}
			/>

			{#if error}
				<p class="error" role="alert" aria-live="assertive">{error}</p>
			{/if}

			<button class="primary-button" type="submit" disabled={isSubmitting}>
				{isSubmitting ? 'Signing in...' : 'Sign in'}
			</button>
		</form>

		<p class="switch">
			New to Zonix? <a href={resolve('/register')}>Create account</a>
		</p>
	</div>
</section>

<style>
	.auth-page {
		display: grid;
		place-items: center;
		padding: 60px 0;
	}

	.auth-card {
		width: min(460px, 100%);
		padding: 30px;
	}

	.auth-card > * {
		position: relative;
		z-index: 1;
	}

	.eyebrow {
		color: var(--accent-2);
		font-weight: 1000;
		text-transform: uppercase;
		font-size: 12px;
		letter-spacing: 0.16em;
	}

	h1 {
		margin: 8px 0;
		font-size: 42px;
		letter-spacing: -0.05em;
	}

	.muted,
	.switch {
		color: var(--text-muted);
	}

	label {
		display: block;
		margin: 18px 0 8px;
		font-weight: 900;
	}

	input {
		width: 100%;
		border: 1px solid var(--border-soft);
		border-radius: 16px;
		padding: 13px 14px;
		color: var(--text-main);
		background: rgba(0, 229, 255, 0.045);
		outline: none;
	}

	.error {
		color: var(--danger);
	}

	button {
		width: 100%;
		margin-top: 20px;
	}

	a {
		color: var(--accent-2);
		text-decoration: none;
		font-weight: 900;
	}
</style>
