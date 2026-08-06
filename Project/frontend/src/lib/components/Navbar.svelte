<!--
  File: src/lib/components/Navbar.svelte
  Purpose: Top navigation bar for the MVP frontend.
  What it does:
  - Displays the Zonix logo asset and links it to the home route.
  - Shows a theme toggle that cycles dark -> light -> system, persisted
    to the signed-in user's profile (guests get a session-only toggle).
  - Shows a clear Sign in link to the /login route.
  Important design decision:
  - The navbar uses the real logo asset while keeping actions simple and understandable.
-->

<script>
  import { fly } from "svelte/transition";

  import zonixLogo from "../../assets/zonix-logo.svg";
  import { authStore } from "$lib/stores/authStore.js";
  import { profileStore } from "$lib/stores/profileStore.js";

  const THEME_CYCLE = ["dark", "light", "system"];
  const THEME_ICONS = { dark: "☾", light: "☼", system: "◐" };

  let guestTheme = $state("system");

  const currentTheme = $derived(
    $authStore.status === "authenticated"
      ? ($profileStore.profile?.theme_preference ?? "system")
      : guestTheme
  );

  async function handleLogout() {
    await authStore.logout();
  }

  async function handleToggleTheme() {
    const next = THEME_CYCLE[(THEME_CYCLE.indexOf(currentTheme) + 1) % THEME_CYCLE.length];

    if ($authStore.status === "authenticated") {
      await profileStore.update({ theme_preference: next });
    } else {
      guestTheme = next;

      if (next === "system") {
        delete document.documentElement.dataset.theme;
      } else {
        document.documentElement.dataset.theme = next;
      }
    }
  }
</script>

<nav class="navbar">
  <a class="logo" href="/" aria-label="Zonix home">
    <img src={zonixLogo} alt="Zonix" />
  </a>

    <div class="links">
  <button
    class="theme-button"
    onclick={handleToggleTheme}
    aria-label={`Theme: ${currentTheme}. Click to change.`}
  >
    {#key currentTheme}
      <span class="theme-icon" in:fly={{ y: -10, duration: 200 }} out:fly={{ y: 10, duration: 200 }}>
        {THEME_ICONS[currentTheme]}
      </span>
    {/key}
  </button>

  {#if $authStore.status === "authenticated" && $authStore.user}
    <a class="secondary-button" href="/feed">Feed</a>
    <a class="secondary-button" href="/friends">Friends</a>
    <a class="user-chip" href="/profile">{$authStore.user.username}</a>
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
    position: relative;
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

  .theme-button:hover {
    color: var(--accent-2);
  }

  .theme-icon {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
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
  text-decoration: none;
}
</style>
