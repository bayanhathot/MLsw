<script>
  import { onMount } from "svelte";

  import MixCard from "$lib/components/MixCard.svelte";
  import {
    getFeed,
    likeMix,
    unlikeMix,
    saveMix,
    unsaveMix
  } from "$lib/services/mixApi.js";

  let mixes = $state([]);
  let loading = $state(true);
  let error = $state("");
  let activeMix = $state(null);
  let activeAudioUrl = $state("");

  onMount(async () => {
    try {
      mixes = await getFeed({ limit: 20, offset: 0 });
    } catch (requestError) {
      error = requestError.message;
    } finally {
      loading = false;
    }
  });

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
    <h1>Discover mixes</h1>
    <p>Listen to mixes created by other Zonix users.</p>
  </header>

  {#if error}
    <div class="error-message" role="alert">
      <span>{error}</span>
      <button type="button" onclick={() => (error = "")}>Close</button>
    </div>
  {/if}

  {#if loading}
    <p class="status-message">Loading mixes...</p>
  {:else if mixes.length === 0}
    <p class="status-message">No published mixes yet.</p>
  {:else}
    <div class="mix-grid">
      {#each mixes as mix (mix.id)}
        <MixCard
          {mix}
          onPlay={handlePlay}
          onLike={handleLike}
          onSave={handleSave}
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
