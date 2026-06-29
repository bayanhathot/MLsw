<!--
  File: src/routes/login/+page.svelte
  Purpose: Login page placeholder for the future signed-in Zonix version.
  What it does:
  - Shows a frontend-only email/password form.
  - Validates that both fields are filled.
  - Logs a placeholder message instead of calling a backend.
  Future behavior:
  - This page should call a backend auth endpoint and store a session/token.
-->

<script>
  /*
    Login page route: /login

    MVP status:
    Frontend-only placeholder. Later this connects to the account system
    for saved sessions, history, and personalization.
  */

  let email = $state("");
  let password = $state("");
  let error = $state("");

  function handleLogin() {
    error = "";

    if (!email.trim() || !password.trim()) {
      error = "Please enter both email and password.";
      return;
    }

    console.log("Zonix login placeholder:", { email });
  }
</script>

<section class="auth-page">
  <div class="auth-card card">
    <p class="eyebrow">Account</p>
    <h1>Sign in.</h1>
    <p class="muted">
      Save sessions, view history, and personalize Zonix when accounts are connected.
    </p>

    <label for="email">Email</label>
    <input id="email" bind:value={email} type="email" placeholder="you@example.com" />

    <label for="password">Password</label>
    <input id="password" bind:value={password} type="password" placeholder="Your password" />

    {#if error}
      <p class="error">{error}</p>
    {/if}

    <button class="primary-button" onclick={handleLogin}>Sign in</button>

    <p class="switch">
      New to Zonix? <a href="/register">Create account</a>
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
