<script>
  /*
    Register page route: /register

    Current MVP:
    - Frontend-only form.
    - No backend auth yet.

    Future:
    - Call POST /auth/register.
    - Create user account.
    - Redirect to login or home.
  */

  let name = $state("");
  let email = $state("");
  let password = $state("");
  let confirmPassword = $state("");
  let error = $state("");

  function handleRegister() {
    error = "";

    if (!name.trim() || !email.trim() || !password.trim()) {
      error = "Please fill all required fields.";
      return;
    }

    if (password !== confirmPassword) {
      error = "Passwords do not match.";
      return;
    }

    console.log("Register placeholder:", { name, email });
  }
</script>

<section class="auth-page">
  <div class="auth-card card">
    <p class="eyebrow">Create account</p>
    <h1>Register</h1>
    <p class="muted">
      Create an account later to save sessions and personalize your AI DJ.
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
      Create account
    </button>

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