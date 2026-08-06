<!--
  File: src/routes/register/+page.svelte
  Purpose: Register page placeholder for future user accounts.
  What it does:
  - Shows a frontend-only account creation form.
  - Validates required fields and matching passwords.
  - Logs a placeholder message instead of calling a backend.
  Future behavior:
  - This page should call a backend register endpoint, then redirect to login or home.
-->

  <script>
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/authStore.js";

  let username = $state("");
  let email = $state("");
  let password = $state("");
  let confirmPassword = $state("");
  let error = $state("");
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

    error = "";

    if (!username.trim() || !email.trim() || !password.trim()) {
      error = "Please fill all required fields.";
      return;
    }

    if (password.length < 6) {
      error = "Password must be at least 6 characters.";
      return;
    }

    if (password !== confirmPassword) {
      error = "Passwords do not match.";
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

      await goto("/");
    } catch (err) {
      error = getErrorMessage(err, "Registration failed.");
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
      Accounts will unlock saved sessions, listening history, and personal settings.
    </p>

    <form onsubmit={handleRegister}>
  <label for="username">Username</label>
  <input id="username" bind:value={username} type="text" placeholder="Your username" />

  <label for="email">Email</label>
  <input id="email" bind:value={email} type="email" placeholder="you@example.com" />

  <label for="password">Password</label>
  <input id="password" bind:value={password} type="password" placeholder="Create password" />

  <label for="confirmPassword">Confirm password</label>
  <input
    id="confirmPassword"
    bind:value={confirmPassword}
    type="password"
    placeholder="Repeat password"
  />

  {#if error}
    <p class="error">{error}</p>
  {/if}

  <button class="primary-button" type="submit" disabled={isSubmitting}>
    {isSubmitting ? "Creating account..." : "Create account"}
  </button>
</form>

    <p class="switch">
      Already have an account? <a href="/login">Sign in</a>
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
