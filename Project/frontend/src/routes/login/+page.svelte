<script>
  /*
    Login page route: /login

    Current MVP:
    - Frontend-only form.
    - No backend auth yet.

    Future:
    - Call POST /auth/login.
    - Store returned session/token.
    - Redirect user after login.
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

    console.log("Login placeholder:", { email });
  }
</script>

<section class="auth-page">
  <div class="auth-card card">
    <p class="eyebrow">Welcome back</p>
    <h1>Sign in</h1>
    <p class="muted">
      Sign in later to save sessions, view history, and personalize your AI DJ.
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
      No account yet? <a href="/register">Create one</a>
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
    width: min(440px, 100%);
    padding: 28px;
  }

  .eyebrow {
    color: var(--accent-2);
    font-weight: 800;
    text-transform: uppercase;
    font-size: 12px;
    letter-spacing: 0.14em;
  }

  h1 {
    margin: 8px 0;
    font-size: 38px;
  }

  .muted,
  .switch {
    color: var(--text-muted);
  }

  label {
    display: block;
    margin: 18px 0 8px;
    font-weight: 700;
  }

  input {
    width: 100%;
    border: 1px solid var(--border-soft);
    border-radius: 14px;
    padding: 13px 14px;
    color: var(--text-main);
    background: rgba(255, 255, 255, 0.08);
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
    font-weight: 700;
  }
</style>