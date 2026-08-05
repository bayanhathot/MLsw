<script>
  import { goto } from "$app/navigation";

  import { authStore } from "$lib/stores/authStore.js";
  import {
    getMyMixes,
    getSavedMixes,
    publishMix,
    unsaveMix,
    updateMix
  } from "$lib/services/mixApi.js";

  let activeTab = $state("mine");
  let myMixes = $state([]);
  let savedMixes = $state([]);
  let loading = $state(true);
  let loaded = $state(false);
  let error = $state("");

  let editingMixId = $state(null);
  let editTitle = $state("");
  let editDescription = $state("");
  let editCoverUrl = $state("");

  let activeMix = $state(null);
  let activeAudioUrl = $state("");

  let displayedMixes = $derived(
    activeTab === "mine" ? myMixes : savedMixes
  );

  $effect(() => {
    if ($authStore.status === "guest") {
      goto("/login");
    }

    if ($authStore.status === "authenticated" && !loaded) {
      loaded = true;
      loadLibrary();
    }
  });

  async function loadLibrary() {
    loading = true;
    error = "";

    try {
      [myMixes, savedMixes] = await Promise.all([
        getMyMixes(),
        getSavedMixes()
      ]);
    } catch (requestError) {
      error = requestError.message;
    } finally {
      loading = false;
    }
  }

  function handlePlay(mix) {
    if (!mix.segments?.length) {
      error = "This mix does not contain playable segments.";
      return;
    }

    activeMix = mix;
    activeAudioUrl = mix.segments[0].audio_url;
  }

  function beginEdit(mix) {
    editingMixId = mix.id;
    editTitle = mix.title;
    editDescription = mix.description ?? "";
    editCoverUrl = mix.cover_url ?? "";
  }

  function cancelEdit() {
    editingMixId = null;
    editTitle = "";
    editDescription = "";
    editCoverUrl = "";
  }

  async function saveEdit(mix) {
    error = "";

    try {
      const updatedMix = await updateMix(mix.id, {
        title: editTitle.trim(),
        description: editDescription.trim() || null,
        cover_url: editCoverUrl.trim() || null
      });

      myMixes = myMixes.map((item) =>
        item.id === updatedMix.id ? updatedMix : item
      );
      cancelEdit();
    } catch (requestError) {
      error = requestError.message;
    }
  }

  async function handlePublish(mix) {
    error = "";

    try {
      const publishedMix = await publishMix(mix.id);
      myMixes = myMixes.map((item) =>
        item.id === publishedMix.id ? publishedMix : item
      );
    } catch (requestError) {
      error = requestError.message;
    }
  }

  async function handleUnsave(mix) {
    error = "";

    try {
      await unsaveMix(mix.id);
      savedMixes = savedMixes.filter((item) => item.id !== mix.id);
    } catch (requestError) {
      error = requestError.message;
    }
  }

  function closePlayer() {
    activeMix = null;
    activeAudioUrl = "";
  }
</script>

<svelte:head>
  <title>Your library | Zonix</title>
</svelte:head>

<section class="library-page">
  <header>
    <p class="eyebrow">Your collection</p>
    <h1>Mix library</h1>
    <p>Manage mixes you created and return to mixes you saved.</p>
  </header>

  <div class="tabs" role="tablist" aria-label="Mix library sections">
    <button
      type="button"
      role="tab"
      aria-selected={activeTab === "mine"}
      class:active={activeTab === "mine"}
      onclick={() => (activeTab = "mine")}
    >
      My mixes
    </button>

    <button
      type="button"
      role="tab"
      aria-selected={activeTab === "saved"}
      class:active={activeTab === "saved"}
      onclick={() => (activeTab = "saved")}
    >
      Saved mixes
    </button>
  </div>

  {#if error}
    <div class="error-message" role="alert">
      <span>{error}</span>
      <button type="button" onclick={() => (error = "")}>Close</button>
    </div>
  {/if}

  {#if $authStore.status === "checking" || loading}
    <p class="status-message">Loading your library...</p>
  {:else if displayedMixes.length === 0}
    <p class="status-message">
      {activeTab === "mine"
        ? "You have not generated any mixes yet."
        : "You have not saved any mixes yet."}
    </p>
  {:else}
    <div class="mix-grid">
      {#each displayedMixes as mix (mix.id)}
        <article class="library-card">
          {#if mix.cover_url}
            <img src={mix.cover_url} alt={`Cover for ${mix.title}`} />
          {:else}
            <div class="cover-placeholder">Z</div>
          {/if}

          <div class="card-content">
            {#if editingMixId === mix.id}
              <label>
                Title
                <input bind:value={editTitle} maxlength="120" />
              </label>

              <label>
                Description
                <textarea bind:value={editDescription} maxlength="1000"></textarea>
              </label>

              <label>
                Cover URL
                <input bind:value={editCoverUrl} type="url" />
              </label>

              <div class="actions">
                <button type="button" onclick={() => saveEdit(mix)}>
                  Save changes
                </button>
                <button type="button" class="secondary" onclick={cancelEdit}>
                  Cancel
                </button>
              </div>
            {:else}
              <div class="card-heading">
                <h2>{mix.title}</h2>

                {#if activeTab === "mine"}
                  <span class:published={mix.status === "published"}>
                    {mix.status === "published" ? "Published" : "Draft"}
                  </span>
                {/if}
              </div>

              <p>{mix.prompt}</p>

              {#if mix.description}
                <p class="description">{mix.description}</p>
              {/if}

              <div class="actions">
                <button type="button" onclick={() => handlePlay(mix)}>Play</button>

                {#if activeTab === "mine" && mix.status === "draft"}
                  <button type="button" class="secondary" onclick={() => beginEdit(mix)}>
                    Edit
                  </button>
                  <button type="button" onclick={() => handlePublish(mix)}>
                    Post mix
                  </button>
                {:else if activeTab === "saved"}
                  <button type="button" class="secondary" onclick={() => handleUnsave(mix)}>
                    Remove saved
                  </button>
                {/if}
              </div>
            {/if}
          </div>
        </article>
      {/each}
    </div>
  {/if}
</section>

{#if activeMix && activeAudioUrl}
  <aside class="library-player">
    <div>
      <span>Now playing</span>
      <strong>{activeMix.title}</strong>
    </div>
    <audio controls autoplay src={activeAudioUrl}></audio>
    <button type="button" onclick={closePlayer}>Close</button>
  </aside>
{/if}

<style>
  .library-page {
    max-width: 1200px;
    margin: 0 auto;
    padding: 3rem 1.5rem 8rem;
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

  header > p:last-child,
  .library-card p,
  .status-message {
    color: #a8b3c7;
  }

  .tabs,
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
  }

  .tabs {
    margin: 2rem 0;
  }

  button {
    padding: 0.65rem 1rem;
    border: 0;
    border-radius: 0.65rem;
    background: #22d3ee;
    color: #07111f;
    font-weight: 700;
    cursor: pointer;
  }

  button.secondary,
  .tabs button {
    border: 1px solid rgba(255, 255, 255, 0.16);
    background: transparent;
    color: #dbeafe;
  }

  .tabs button.active {
    border-color: #22d3ee;
    background: rgba(34, 211, 238, 0.12);
    color: #67e8f9;
  }

  .mix-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 1.25rem;
  }

  .library-card {
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 1rem;
    background: rgba(15, 23, 42, 0.88);
  }

  .library-card > img,
  .cover-placeholder {
    width: 100%;
    aspect-ratio: 16 / 9;
  }

  .library-card > img {
    display: block;
    object-fit: cover;
  }

  .cover-placeholder {
    display: grid;
    place-items: center;
    background: linear-gradient(135deg, #10243c, #07111f);
    color: #67e8f9;
    font-size: 3rem;
    font-weight: 800;
  }

  .card-content {
    padding: 1rem;
  }

  .card-heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
  }

  h2 {
    margin: 0;
    color: #f8fafc;
    font-size: 1.2rem;
  }

  .card-heading span {
    padding: 0.25rem 0.5rem;
    border-radius: 999px;
    background: rgba(148, 163, 184, 0.14);
    color: #cbd5e1;
    font-size: 0.75rem;
  }

  .card-heading span.published {
    background: rgba(34, 197, 94, 0.14);
    color: #86efac;
  }

  label {
    display: grid;
    gap: 0.35rem;
    margin-bottom: 0.8rem;
    color: #dbeafe;
  }

  input,
  textarea {
    width: 100%;
    box-sizing: border-box;
    padding: 0.7rem;
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 0.6rem;
    background: #0b1220;
    color: #f8fafc;
  }

  textarea {
    min-height: 6rem;
    resize: vertical;
  }

  .error-message,
  .library-player {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem;
    border-radius: 1rem;
  }

  .error-message {
    margin-bottom: 1rem;
    background: rgba(127, 29, 29, 0.25);
    color: #fecaca;
  }

  .library-player {
    position: fixed;
    right: 1rem;
    bottom: 1rem;
    left: 1rem;
    z-index: 20;
    border: 1px solid rgba(34, 211, 238, 0.35);
    background: #0f172a;
    color: #f8fafc;
  }

  .library-player div {
    display: flex;
    flex-direction: column;
  }

  .library-player span {
    color: #67e8f9;
    font-size: 0.75rem;
  }

  .library-player audio {
    width: min(500px, 60%);
  }

  @media (max-width: 700px) {
    .library-player {
      flex-wrap: wrap;
    }

    .library-player audio {
      order: 3;
      width: 100%;
    }
  }
</style>
