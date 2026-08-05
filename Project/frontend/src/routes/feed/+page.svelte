<script>
  import { onMount } from "svelte";

  import MixCard from "$lib/components/MixCard.svelte";
  import {
    getFeed,
    followUser,
    likeMix,
    unlikeMix,
    saveMix,
    unsaveMix,
    unfollowUser
  } from "$lib/services/mixApi.js";

  let mixes = $state([]);
  let loading = $state(true);
  let error = $state("");
  let activeMix = $state(null);
  let activeAudioUrl = $state("");
  let activeScope = $state("friends");

  onMount(async () => {
    await loadFeed();
  });

  async function loadFeed() {
    loading = true;
    error = "";

    try {
      mixes = await getFeed({
        limit: 20,
        offset: 0,
        scope: activeScope
      });
    } catch (requestError) {
      error = requestError.message;
    } finally {
      loading = false;
    }
  }

  async function selectScope(scope) {
    if (scope === activeScope) {
      return;
    }

    activeScope = scope;
    await loadFeed();
  }

  function handlePlay(mix) {
    if (!mix.segments?.length) {
      error = "This mix does not contain playable segments.";
      return;
    }

    activeMix = mix;
    activeAudioUrl = mix.segments[0].audio_url;
  }

  async function handleLike(mix) {
    const previousLiked = mix.is_liked;
    const previousCount = mix.like_count;

    mix.is_liked = !mix.is_liked;
    mix.like_count = Math.max(
      0,
      mix.like_count + (mix.is_liked ? 1 : -1)
    );
    mixes = [...mixes];

    try {
      const result = mix.is_liked
        ? await likeMix(mix.id)
        : await unlikeMix(mix.id);

      mix.is_liked = result.is_liked;
      mix.like_count = result.like_count;
      mixes = [...mixes];
    } catch (requestError) {
      mix.is_liked = previousLiked;
      mix.like_count = previousCount;
      mixes = [...mixes];
      error = requestError.message;
    }
  }

  async function handleSave(mix) {
    const previousSaved = mix.is_saved;

    mix.is_saved = !mix.is_saved;
    mixes = [...mixes];

    try {
      const result = mix.is_saved
        ? await saveMix(mix.id)
        : await unsaveMix(mix.id);

      mix.is_saved = result.is_saved;
      mixes = [...mixes];
    } catch (requestError) {
      mix.is_saved = previousSaved;
      mixes = [...mixes];
      error = requestError.message;
    }
  }

  async function handleFollow(mix) {
    const ownerId = mix.owner.id;
    const previousFollowing = mix.is_following;
    const nextFollowing = !previousFollowing;

    mixes = mixes.map((item) =>
      item.owner.id === ownerId
        ? {
            ...item,
            is_following: nextFollowing,
            is_friend: nextFollowing && item.follows_you
          }
        : item
    );

    try {
      const result = nextFollowing
        ? await followUser(ownerId)
        : await unfollowUser(ownerId);

      if (activeScope === "friends" && !result.is_following) {
        mixes = mixes.filter((item) => item.owner.id !== ownerId);
      } else {
        mixes = mixes.map((item) =>
          item.owner.id === ownerId
            ? {
                ...item,
                is_following: result.is_following,
                is_friend: result.is_following && item.follows_you
              }
            : item
        );
      }
    } catch (requestError) {
      mixes = mixes.map((item) =>
        item.owner.id === ownerId
          ? {
              ...item,
              is_following: previousFollowing,
              is_friend: previousFollowing && item.follows_you
            }
          : item
      );
      error = requestError.message;
    }
  }

  function closePlayer() {
    activeMix = null;
    activeAudioUrl = "";
  }
</script>

<svelte:head>
  <title>Community mixes | Zonix</title>
</svelte:head>

<section class="feed-page">
  <header class="feed-header">
    <p class="eyebrow">Zonix community</p>
    <h1>
      {activeScope === "friends"
        ? "Friends"
        : "Discover mixes"}
    </h1>
    <p>
      {activeScope === "friends"
        ? "New mixes from creators who follow you back."
        : "Find creators and mixes from across Zonix."}
    </p>
  </header>

  <div class="feed-tabs" aria-label="Community feed type">
    <button
      type="button"
      class:active={activeScope === "friends"}
      aria-pressed={activeScope === "friends"}
      onclick={() => selectScope("friends")}
    >
      Friends
    </button>
    <button
      type="button"
      class:active={activeScope === "discover"}
      aria-pressed={activeScope === "discover"}
      onclick={() => selectScope("discover")}
    >
      Discover
    </button>
  </div>

  {#if error}
    <div class="error-message" role="alert">
      <span>{error}</span>
      <button type="button" onclick={() => (error = "")}>Close</button>
    </div>
  {/if}

  {#if loading}
    <p class="status-message">Loading mixes...</p>
  {:else if mixes.length === 0}
    <div class="empty-feed">
      <p class="status-message">
        {activeScope === "friends"
          ? "Friends appear when you and another creator follow each other."
          : "No published mixes yet."}
      </p>
      {#if activeScope === "friends"}
        <button type="button" onclick={() => selectScope("discover")}>Explore Discover</button>
      {/if}
    </div>
  {:else}
    <div class="mix-grid">
      {#each mixes as mix (mix.id)}
        <MixCard
          {mix}
          onPlay={handlePlay}
          onLike={handleLike}
          onSave={handleSave}
          onFollow={handleFollow}
        />
      {/each}
    </div>
  {/if}
</section>

{#if activeMix && activeAudioUrl}
  <aside class="feed-player">
    <div>
      <span>Now playing</span>
      <strong>{activeMix.title}</strong>
    </div>

    <audio controls autoplay src={activeAudioUrl}></audio>

    <button type="button" aria-label="Close player" onclick={closePlayer}>
      Close
    </button>
  </aside>
{/if}

<style>
  .feed-page {
    max-width: 1200px;
    margin: 0 auto;
    padding: 3rem 1.5rem 8rem;
  }

  .feed-header {
    margin-bottom: 2rem;
  }

  .feed-tabs {
    display: flex;
    gap: 0.65rem;
    margin-bottom: 1.5rem;
  }

  .feed-tabs button,
  .empty-feed button {
    padding: 0.7rem 1rem;
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 999px;
    background: transparent;
    color: #dbeafe;
    font-weight: 700;
    cursor: pointer;
  }

  .feed-tabs button.active,
  .empty-feed button {
    border-color: #22d3ee;
    background: rgba(34, 211, 238, 0.12);
    color: #67e8f9;
  }

  .eyebrow {
    margin: 0;
    color: #67e8f9;
    font-weight: 700;
  }

  h1 {
    margin: 0.4rem 0;
    color: #f8fafc;
    font-size: clamp(2rem, 5vw, 3.5rem);
  }

  .feed-header > p:last-child,
  .status-message {
    color: #a8b3c7;
  }

  .empty-feed {
    display: grid;
    justify-items: center;
    padding: 2rem 0;
  }

  .empty-feed .status-message {
    padding: 1rem 0;
  }

  .mix-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 1.25rem;
  }

  .status-message {
    padding: 3rem 0;
    text-align: center;
  }

  .error-message {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
    padding: 1rem;
    border: 1px solid rgba(248, 113, 113, 0.4);
    border-radius: 0.75rem;
    background: rgba(127, 29, 29, 0.25);
    color: #fecaca;
  }

  .feed-player {
    position: fixed;
    right: 1rem;
    bottom: 1rem;
    left: 1rem;
    z-index: 20;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem;
    border: 1px solid rgba(34, 211, 238, 0.35);
    border-radius: 1rem;
    background: #0f172a;
    color: #f8fafc;
  }

  .feed-player div {
    display: flex;
    flex-direction: column;
  }

  .feed-player span {
    color: #67e8f9;
    font-size: 0.75rem;
  }

  .feed-player audio {
    width: min(500px, 60%);
  }

  @media (max-width: 700px) {
    .feed-player {
      flex-wrap: wrap;
    }

    .feed-player audio {
      order: 3;
      width: 100%;
    }
  }
</style>
