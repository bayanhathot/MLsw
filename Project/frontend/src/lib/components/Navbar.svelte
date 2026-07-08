<!--
  File: src/lib/components/Navbar.svelte
  Purpose: Top navigation bar for the MVP frontend.
  What it does:
  - Displays the Zonix logo asset and links it to the home route.
  - Shows a placeholder theme button for future light/dark or appearance switching.
  - Shows a clear Sign in link to the /login route.
  Important design decision:
  - The navbar uses the real logo asset while keeping actions simple and understandable.
-->

<script>
  import zonixLogo from "../../assets/zonix-logo.svg";
  import { authStore } from "$lib/stores/authStore.js";

  async function handleLogout() {
    await authStore.logout();
  }
</script>

<nav class="navbar">
  <a class="logo" href="/" aria-label="Zonix home">
    <img src={zonixLogo} alt="Zonix" />
  </a>

    <div class="links">
  <button class="theme-button" aria-label="Theme toggle placeholder">☼</button>

  {#if $authStore.status === "authenticated" && $authStore.user}
    <span class="user-chip">{$authStore.user.username}</span>
    <button class="secondary-button" type="button" onclick={handleLogout}>Logout</button>
  {:else if $authStore.status === "checking"}
    <span class="user-chip">Checking...</span>
  {:else}
    <a class="secondary-button" href="/login">Sign in</a>
  {/if}
</div>
</nav>

<style>
  .navbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 0 14px;
  }

  .logo {
    display: inline-flex;
    align-items: center;
    width: 190px;
    min-width: 0;
    text-decoration: none;
  }

  .logo img {
    width: 100%;
    height: auto;
    display: block;
  }

  .links {
    display: flex;
    align-items: center;
    gap: 18px;
  }

  .theme-button {
    width: 42px;
    height: 42px;
    display: grid;
    place-items: center;
    border: none;
    color: var(--text-soft);
    background: transparent;
    font-size: 30px;
    line-height: 1;
  }

  @media (max-width: 560px) {
    .logo {
      width: 150px;
    }

    .theme-button {
      display: none;
    }
  }
  .user-chip {
  border: 1px solid var(--border-muted);
  border-radius: 999px;
  padding: 10px 14px;
  color: var(--text-soft);
  background: rgba(255, 255, 255, 0.025);
  font-size: 14px;
  font-weight: 900;
}
</style>
