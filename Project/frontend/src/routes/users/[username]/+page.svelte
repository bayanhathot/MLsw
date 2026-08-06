<!--
  File: src/routes/users/[username]/+page.svelte
  Purpose: Public profile page for another user (or yourself).

  Phase 1 scope:
  Only fields derived from the users table (username, created_at) plus
  friend status. Later phases extend this page with posts and profile
  customization, without changing this shape.
-->

<script>
  import { page } from "$app/stores";
  import PostCard from "$lib/components/PostCard.svelte";
  import { deletePost, likePost, sharePost, unlikePost } from "$lib/services/postsApi.js";
  import { getUserStats } from "$lib/services/profileApi.js";
  import { getUserPosts, getUserProfile } from "$lib/services/usersApi.js";
  import { authStore } from "$lib/stores/authStore.js";
  import { friendsStore } from "$lib/stores/friendsStore.js";
  import { parseUtcDate } from "$lib/utils/dates.js";

  /** @type {import("$lib/services/profileApi.js").ProfileStats | null} */
  let stats = $state(null);
  let statsStatus = $state("loading");

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

  /**
   * @param {number} minutes
   */
  function formatMinutes(minutes) {
    if (minutes < 60) return `${minutes} min`;

    const hours = Math.floor(minutes / 60);
    const remaining = minutes % 60;

    return remaining > 0 ? `${hours}h ${remaining}m` : `${hours}h`;
  }

  /** @type {import("$lib/services/usersApi.js").UserProfilePage | null} */
  let profile = $state(null);
  let status = $state("loading");
  let error = $state("");

  /** @type {import("$lib/services/postsApi.js").Post[]} */
  let posts = $state([]);
  let postsStatus = $state("loading");

  /**
   * @param {string} username
   */
  async function loadProfile(username) {
    status = "loading";
    error = "";

    try {
      profile = await getUserProfile(username);
      status = "ready";
    } catch (err) {
      error = err instanceof Error ? err.message : "Failed to load profile.";
      status = "error";
    }
  }

  /**
   * @param {string} username
   */
  async function loadPosts(username) {
    postsStatus = "loading";

    try {
      posts = await getUserPosts(username);
      postsStatus = "ready";
    } catch {
      postsStatus = "error";
    }
  }

  $effect(() => {
    loadProfile($page.params.username);
    loadPosts($page.params.username);
    loadStats($page.params.username);
  });

  /**
   * @param {number} postId
   */
  function removePostLocally(postId) {
    posts = posts.filter((post) => post.id !== postId);
  }

  /**
   * @param {number} postId
   * @param {import("$lib/services/postsApi.js").Post} updated
   */
  function replacePostLocally(postId, updated) {
    posts = posts.map((post) => (post.id === postId ? updated : post));
  }

  /**
   * @param {number} postId
   */
  async function handleLike(postId) {
    replacePostLocally(postId, await likePost(postId));
  }

  /**
   * @param {number} postId
   */
  async function handleUnlike(postId) {
    replacePostLocally(postId, await unlikePost(postId));
  }

  /**
   * @param {number} postId
   */
  async function handleShare(postId) {
    const { share_count } = await sharePost(postId);
    posts = posts.map((post) => (post.id === postId ? { ...post, share_count } : post));
  }

  /**
   * @param {number} postId
   */
  async function handleDelete(postId) {
    await deletePost(postId);
    removePostLocally(postId);
  }

  async function handleSendRequest() {
    if (!profile) return;

    await friendsStore.sendRequest(profile.username);
    profile = { ...profile, friend_status: "pending_outgoing" };
  }

  async function handleUnfriend() {
    if (!profile) return;

    await friendsStore.remove(profile.username);
    profile = { ...profile, friend_status: "none" };
  }

  /**
   * @param {string} iso
   */
  function formatJoinDate(iso) {
    try {
      return parseUtcDate(iso).toLocaleDateString(undefined, { year: "numeric", month: "long" });
    } catch {
      return iso;
    }
  }
</script>

<section class="profile-page">
  {#if status === "loading"}
    <p class="muted">Loading profile...</p>
  {:else if status === "error"}
    <p class="error">{error}</p>
  {:else if profile}
    <div class="card profile-card">
      <div class="identity-row">
        {#if profile.avatar_url}
          <img class="avatar" src={profile.avatar_url} alt={`${profile.username}'s avatar`} />
        {:else}
          <div class="avatar placeholder">{profile.username.slice(0, 2).toUpperCase()}</div>
        {/if}

        <div>
          <p class="eyebrow">Profile</p>
          <h1>{profile.display_name || profile.username}</h1>
          {#if profile.display_name}
            <p class="muted">@{profile.username}</p>
          {/if}
        </div>
      </div>

      {#if profile.bio}
        <p class="bio">{profile.bio}</p>
      {/if}

      {#if profile.favorite_genres && profile.favorite_genres.length > 0}
        <div class="genre-chips">
          {#each profile.favorite_genres as genre}
            <span class="badge genre-chip">{genre}</span>
          {/each}
        </div>
      {/if}

      <p class="muted joined">Joined {formatJoinDate(profile.created_at)}</p>

      {#if statsStatus === "ready" && stats}
        <p class="stats-line">
          {formatMinutes(stats.minutes_listened)} listened
          {#if stats.favorite_artists.length > 0}
            &middot; favorite artist: {stats.favorite_artists[0].artist}
          {/if}
        </p>
      {/if}

      <div class="action-row">
        {#if profile.friend_status === "self"}
          <span class="status-chip">This is you</span>
          <a class="secondary-button" href="/profile">Edit profile</a>
        {:else if profile.friend_status === "none"}
          <button class="primary-button" onclick={handleSendRequest}>Add Friend</button>
        {:else if profile.friend_status === "pending_outgoing"}
          <span class="status-chip">Friend request sent</span>
        {:else if profile.friend_status === "pending_incoming"}
          <span class="status-chip">
            Sent you a friend request - <a href="/friends">respond here</a>
          </span>
        {:else if profile.friend_status === "friends"}
          <span class="status-chip friends">Friends</span>
          <button class="secondary-button" onclick={handleUnfriend}>Unfriend</button>
        {/if}
      </div>
    </div>

    <div class="posts-section">
      <p class="eyebrow">Posts</p>

      {#if postsStatus === "loading"}
        <p class="muted">Loading posts...</p>
      {:else if postsStatus === "error"}
        <p class="error">Failed to load posts.</p>
      {:else if posts.length === 0}
        <p class="muted">No posts yet.</p>
      {:else}
        <div class="post-list">
          {#each posts as post (post.id)}
            <PostCard
              {post}
              currentUsername={$authStore.user?.username ?? null}
              onLike={handleLike}
              onUnlike={handleUnlike}
              onShare={handleShare}
              onDelete={handleDelete}
            />
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</section>

<style>
  .profile-page {
    display: grid;
    gap: 24px;
    max-width: 720px;
    margin: 0 auto;
    padding: 30px 0 60px;
  }

  .profile-card {
    padding: 30px;
  }

  .identity-row {
    display: flex;
    align-items: center;
    gap: 18px;
  }

  .avatar {
    width: 64px;
    height: 64px;
    flex: 0 0 auto;
    border-radius: 999px;
    object-fit: cover;
    border: 1px solid rgba(125, 183, 255, 0.24);
  }

  .avatar.placeholder {
    display: grid;
    place-items: center;
    color: white;
    background: linear-gradient(135deg, #264984, #6ea9ff);
    font-weight: 1000;
    letter-spacing: 0.04em;
  }

  .bio {
    margin: 16px 0 0;
    color: var(--text-soft);
  }

  .genre-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 14px;
  }

  .genre-chip {
    text-transform: none;
    letter-spacing: normal;
    border: 1px solid var(--border-muted);
    border-radius: 999px;
    padding: 6px 12px;
  }

  .genre-chip::before {
    display: none;
  }

  .joined {
    margin-top: 14px;
  }

  .stats-line {
    margin: 8px 0 0;
    color: var(--text-soft);
    font-size: 14px;
  }

  .posts-section {
    display: grid;
    gap: 16px;
  }

  .post-list {
    display: grid;
    gap: 20px;
  }

  .eyebrow {
    margin: 0 0 6px;
    color: var(--accent-2);
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }

  h1 {
    margin: 0 0 6px;
    font-size: 34px;
    letter-spacing: -0.04em;
  }

  .muted {
    color: var(--text-muted);
  }

  .error {
    color: var(--danger);
  }

  .action-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 20px;
  }

  .status-chip {
    color: var(--text-muted);
    font-weight: 800;
  }

  .status-chip.friends {
    color: var(--success);
  }

  .status-chip a {
    color: var(--accent-2);
  }
</style>
