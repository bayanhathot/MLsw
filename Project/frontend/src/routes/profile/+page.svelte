<!--
  File: src/routes/profile/+page.svelte
  Purpose: Edit your own profile (display name, avatar, bio, favorite
  genres, theme) and see your listening stats.
-->

<script>
  import { onMount } from "svelte";

  import { getUserStats } from "$lib/services/profileApi.js";
  import { authStore } from "$lib/stores/authStore.js";
  import { profileStore } from "$lib/stores/profileStore.js";

  let displayName = $state("");
  let avatarUrl = $state("");
  let bio = $state("");
  let genresText = $state("");
  /** @typedef {import("$lib/services/profileApi.js").ThemePreference} ThemePreference */

  /** @type {ThemePreference[]} */
  const THEME_OPTIONS = ["dark", "light", "system"];

  /** @type {ThemePreference} */
  let themePreference = $state("dark");

  let isSaving = $state(false);
  let saveError = $state("");
  let saved = $state(false);

  /** @type {import("$lib/services/profileApi.js").ProfileStats | null} */
  let stats = $state(null);
  let statsStatus = $state("loading");

  function syncFormFromProfile() {
    const profile = $profileStore.profile;
    if (!profile) return;

    displayName = profile.display_name ?? "";
    avatarUrl = profile.avatar_url ?? "";
    bio = profile.bio ?? "";
    genresText = (profile.favorite_genres ?? []).join(", ");
    themePreference = profile.theme_preference;
  }

  /**
   * @param {string} username
   */
  async function loadStats(username) {
    statsStatus = "loading";

    try {
      stats = await getUserStats(username);
      statsStatus = "ready";
    } catch {
      statsStatus = "error";
    }
  }

  onMount(async () => {
    await profileStore.load();
    syncFormFromProfile();
  });

  // authStore.checkAuth() (triggered by the root layout) resolves
  // asynchronously, so $authStore.user may still be null when this page
  // first mounts - react to it becoming available instead of reading it
  // once in onMount.
  $effect(() => {
    const username = $authStore.user?.username;

    if (username) {
      loadStats(username);
    }
  });

  /**
   * @param {SubmitEvent} event
   */
  async function handleSubmit(event) {
    event.preventDefault();

    saveError = "";
    saved = false;
    isSaving = true;

    const genres = genresText
      .split(",")
      .map((genre) => genre.trim())
      .filter(Boolean);

    try {
      await profileStore.update({
        display_name: displayName.trim() || null,
        avatar_url: avatarUrl.trim() || null,
        bio: bio.trim() || null,
        favorite_genres: genres.length > 0 ? genres : null,
        theme_preference: themePreference
      });
      saved = true;
    } catch (err) {
      saveError = err instanceof Error ? err.message : "Failed to save profile.";
    } finally {
      isSaving = false;
    }
  }

  /**
   * @param {number} minutes
   */
  function formatMinutes(minutes) {
    if (minutes < 60) return `${minutes} min`;

    const hours = Math.floor(minutes / 60);
    const remaining = minutes % 60;

    return remaining > 0 ? `${hours}h ${remaining}m` : `${hours}h`;
  }
</script>

<section class="profile-edit-page">
  <div class="card edit-card">
    <p class="eyebrow">Your profile</p>

    <form onsubmit={handleSubmit}>
      <label for="display-name">Display name</label>
      <input id="display-name" bind:value={displayName} type="text" placeholder={$authStore.user?.username ?? ""} />

      <label for="avatar-url">Avatar URL</label>
      <input id="avatar-url" bind:value={avatarUrl} type="text" placeholder="https://..." />

      <label for="bio">Bio</label>
      <textarea id="bio" bind:value={bio} maxlength="280" placeholder="A little about your taste in music"></textarea>

      <label for="genres">Favorite genres</label>
      <input id="genres" bind:value={genresText} type="text" placeholder="lofi, house, jazz" />

      <span class="field-label">Theme</span>
      <div class="theme-options">
        {#each THEME_OPTIONS as option}
          <button
            type="button"
            class="theme-option"
            class:active={themePreference === option}
            onclick={() => (themePreference = option)}
          >
            {option}
          </button>
        {/each}
      </div>

      {#if saveError}
        <p class="error">{saveError}</p>
      {/if}
      {#if saved}
        <p class="success">Profile saved.</p>
      {/if}

      <button class="primary-button" type="submit" disabled={isSaving}>
        {isSaving ? "Saving..." : "Save profile"}
      </button>
    </form>
  </div>

  <div class="card stats-card">
    <p class="eyebrow">Listening stats</p>

    {#if statsStatus === "loading"}
      <p class="muted">Loading stats...</p>
    {:else if statsStatus === "error"}
      <p class="error">Failed to load stats.</p>
    {:else if stats}
      <p class="minutes">{formatMinutes(stats.minutes_listened)} listened</p>

      {#if stats.favorite_artists.length > 0}
        <div class="artist-list">
          {#each stats.favorite_artists as artist}
            <div class="artist-row">
              <span class="artist-name">{artist.artist}</span>
              <span class="artist-time">{formatMinutes(Math.round(artist.seconds_listened / 60))}</span>
            </div>
          {/each}
        </div>
      {:else}
        <p class="muted">Listen to a mix to start building your favorite artists.</p>
      {/if}
    {/if}
  </div>
</section>

<style>
  .profile-edit-page {
    display: grid;
    gap: 20px;
    max-width: 640px;
    margin: 0 auto;
    padding: 30px 0 60px;
  }

  .edit-card,
  .stats-card {
    padding: 24px;
  }

  .eyebrow {
    margin: 0 0 14px;
    color: var(--accent-2);
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }

  form {
    display: grid;
    gap: 6px;
  }

  label,
  .field-label {
    color: var(--text-soft);
    font-weight: 800;
    font-size: 13px;
    margin-top: 12px;
  }

  input,
  textarea {
    width: 100%;
    border: 1px solid var(--border-muted);
    border-radius: 14px;
    padding: 12px 16px;
    color: var(--text-main);
    background: rgba(0, 0, 0, 0.22);
    outline: none;
    font: inherit;
  }

  textarea {
    min-height: 80px;
    resize: vertical;
  }

  input:focus,
  textarea:focus {
    border-color: rgba(125, 183, 255, 0.42);
  }

  .theme-options {
    display: flex;
    gap: 8px;
  }

  .theme-option {
    border: 1px solid var(--border-muted);
    border-radius: 999px;
    padding: 8px 16px;
    color: var(--text-soft);
    background: rgba(255, 255, 255, 0.025);
    text-transform: capitalize;
    font-size: 13px;
    font-weight: 800;
  }

  .theme-option.active {
    border-color: var(--accent-2);
    color: var(--text-main);
    background: rgba(59, 130, 246, 0.16);
  }

  .error {
    color: var(--danger);
    margin: 8px 0 0;
  }

  .success {
    color: var(--success);
    margin: 8px 0 0;
  }

  button[type="submit"] {
    margin-top: 16px;
  }

  .muted {
    color: var(--text-muted);
  }

  .minutes {
    margin: 0 0 14px;
    color: var(--text-main);
    font-size: 20px;
    font-weight: 900;
  }

  .artist-list {
    display: grid;
    gap: 8px;
  }

  .artist-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    border: 1px solid var(--border-muted);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.02);
  }

  .artist-name {
    color: var(--text-main);
    font-weight: 800;
  }

  .artist-time {
    color: var(--text-muted);
    font-size: 13px;
  }
</style>
