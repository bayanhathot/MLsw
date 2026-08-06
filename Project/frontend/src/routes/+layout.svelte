<!--
  File: src/routes/+layout.svelte
  Purpose: Root SvelteKit layout shared by all pages.
  What it does:
  - Imports global CSS once for the whole app.
  - Renders the Navbar above every route.
  - Provides the main centered app shell width.
  - Uses Svelte 5 {@render children()} to display the active route page.
  Why this file exists:
  - In SvelteKit, +layout.svelte replaces the old Vite App.svelte outer shell.
-->

<script>
  import { onMount } from "svelte";

  import "../app.css";
  import Navbar from "$lib/components/Navbar.svelte";
  import { authStore } from "$lib/stores/authStore.js";
  import { profileStore } from "$lib/stores/profileStore.js";

  let { children } = $props();

  onMount(() => {
    authStore.checkAuth();
  });

  // Load the profile (for theme_preference) once we know who's logged in.
  $effect(() => {
    if ($authStore.status === "authenticated") {
      profileStore.load();
    }
  });

  // Apply the stored theme choice to the document. "system"/no profile
  // means: don't force anything, let the prefers-color-scheme CSS decide.
  $effect(() => {
    const theme = $profileStore.profile?.theme_preference;

    if (theme && theme !== "system") {
      document.documentElement.dataset.theme = theme;
    } else {
      delete document.documentElement.dataset.theme;
    }
  });
</script>

<div class="app-shell">
  <Navbar />

  {@render children()}
</div>

<style>
  .app-shell {
    width: min(1500px, calc(100% - 32px));
    margin: 0 auto;
  }
</style>