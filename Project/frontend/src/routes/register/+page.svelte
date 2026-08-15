<!--
  File: src/routes/register/+page.svelte
  Purpose: Registration page for Cuemix accounts.
  What it does:
  - Validates the form, creates an account, signs in, and redirects home.
-->

<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { authStore } from '$lib/stores/authStore.js';

	let username = $state('');
	let email = $state('');
	let password = $state('');
	let confirmPassword = $state('');
	let error = $state('');
	let isSubmitting = $state(false);

	/**
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
	async function handleRegister(event) {
		event.preventDefault();

		error = '';

		if (!username.trim() || !email.trim() || !password.trim()) {
			error = 'Please fill all required fields.';
			return;
		}

		if (password !== confirmPassword) {
			error = 'Passwords do not match.';
			return;
		}

		isSubmitting = true;

		try {
			await authStore.register({
				username: username.trim(),
				email: email.trim(),
				password
			});

			await authStore.login({
				email: email.trim(),
				password
			});

			await goto(resolve('/'));
		} catch (err) {
			error = getErrorMessage(err, 'Registration failed.');
		} finally {
			isSubmitting = false;
		}
	}
</script>

<section class="auth-page">
	<div class="auth-card card">
		<p class="eyebrow">Create account</p>
		<h1>Register.</h1>
		<p class="muted">
			Keep generated mixes, save community picks, and personalize future sessions.
		</p>

		<form onsubmit={handleRegister}>
			<label for="username">Username</label>
			<input
				id="username"
				bind:value={username}
				type="text"
				placeholder="Your username"
				autocomplete="username"
				minlength="3"
				maxlength="50"
				pattern="[A-Za-z0-9_.-]+"
				title="Use letters, numbers, dots, underscores, or hyphens."
				required
				disabled={isSubmitting}
			/>

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
				placeholder="Create password"
				autocomplete="new-password"
				minlength="8"
				maxlength="72"
				required
				disabled={isSubmitting}
			/>

			<label for="confirmPassword">Confirm password</label>
			<input
				id="confirmPassword"
				bind:value={confirmPassword}
				type="password"
				placeholder="Repeat password"
				autocomplete="new-password"
				minlength="8"
				maxlength="72"
				required
				disabled={isSubmitting}
			/>

			{#if error}
				<p class="error" role="alert" aria-live="assertive">{error}</p>
			{/if}

			<button class="primary-button" type="submit" disabled={isSubmitting}>
				{isSubmitting ? 'Creating account...' : 'Create account'}
			</button>
		</form>

		<p class="switch">
			Already have an account? <a href={resolve('/login')}>Sign in</a>
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
