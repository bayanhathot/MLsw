<script>
  /*
    Register page route: /register

    MVP status:
    Frontend-only placeholder. Later this creates a profile for
    saved sessions and personalization.
  */

  let name = $state("");
  let email = $state("");
  let password = $state("");
  let confirmPassword = $state("");
  let error = $state("");

  function handleRegister() {
    error = "";

    if (!name.trim() || !email.trim() || !password.trim()) {
      error = "Fill the required fields to create your vault.";
      return;
    }

    if (password !== confirmPassword) {
      error = "Passwords do not match.";
      return;
    }

    console.log("Zonix register placeholder:", { name, email });
  }
</script>

<section class="auth-page">
  <div class="auth-card card">
    <p class="eyebrow">Create vault</p>
    <h1>Register.</h1>
    <p class="muted">
      Accounts will unlock saved sessions, listening history, and personal settings.
    </p>

    <label for="name">Name</label>
    <input id="name" bind:value={name} type="text" placeholder="Your name" />

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

    <button class="primary-button" onclick={handleRegister}>
      Create vault
    </button>

    <p class="switch">
      Already locked in? <a href="/login">Sign in</a>
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
