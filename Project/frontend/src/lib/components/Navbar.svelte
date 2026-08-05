<!--
  File: src/lib/components/Navbar.svelte
  Purpose: Top navigation bar for the MVP frontend.
  What it does:
  - Displays the Zonix logo asset and links it to the home route.
  - Connects the home, community feed, and personal library routes.
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
  <div class="navigation" aria-label="Main navigation">
    <a class="nav-link" href="/">Home</a>

    {#if $authStore.status === "authenticated"}
      <a class="nav-link" href="/feed">Community</a>
      <a class="nav-link" href="/library">Library</a>
    {/if}
  </div>

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
    margin-left: auto;
  }

  .navigation {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .nav-link {
    padding: 10px 12px;
    border-radius: 999px;
    color: var(--text-soft);
    font-size: 14px;
    font-weight: 850;
    text-decoration: none;
    transition: color 160ms ease, background 160ms ease;
  }

  .nav-link:hover,
  .nav-link:focus-visible {
    color: white;
    background: rgba(59, 130, 246, 0.14);
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
    .navbar,
    .links,
    .navigation {
      flex-wrap: wrap;
    }

    .links {
      justify-content: flex-end;
      gap: 10px;
    }

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
