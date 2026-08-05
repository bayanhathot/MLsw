<script>
  /** Display one published mix and report its actions to the feed page. */
  let { mix, onPlay, onLike, onSave, onFollow } = $props();
</script>

<article class="mix-card">
  <div class="cover-area">
    {#if mix.cover_url}
      <img class="mix-cover" src={mix.cover_url} alt={`Cover for ${mix.title}`} />
    {:else}
      <div class="cover-placeholder">Z</div>
    {/if}
  </div>

  <div class="mix-content">
    <div class="owner-row">
      <div class="mix-owner">by @{mix.owner.username}</div>

      {#if !mix.is_own}
        <button
          class="follow-button"
          class:active={mix.is_following}
          type="button"
          aria-pressed={mix.is_following}
          onclick={() => onFollow(mix)}
        >
          {mix.is_friend
            ? "Friends"
            : mix.is_following
              ? "Following"
              : mix.follows_you
                ? "Follow back"
                : "Follow"}
        </button>
      {/if}
    </div>
    <h2>{mix.title}</h2>
    <p class="prompt">{mix.prompt}</p>

    {#if mix.description}
      <p class="description">{mix.description}</p>
    {/if}

    <div class="mix-actions">
      <button class="play-button" type="button" onclick={() => onPlay(mix)}>
        Play
      </button>

      <button
        class="social-button"
        class:active={mix.is_liked}
        type="button"
        aria-label={mix.is_liked ? "Unlike mix" : "Like mix"}
        aria-pressed={mix.is_liked}
        onclick={() => onLike(mix)}
      >
        <span>{mix.is_liked ? "Liked" : "Like"}</span>
        <span>{mix.like_count}</span>
      </button>

      <button
        class="social-button"
        class:active={mix.is_saved}
        type="button"
        aria-label={mix.is_saved ? "Remove saved mix" : "Save mix"}
        aria-pressed={mix.is_saved}
        onclick={() => onSave(mix)}
      >
        {mix.is_saved ? "Saved" : "Save"}
      </button>
    </div>
  </div>
</article>

<style>
  .mix-card {
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 1rem;
    background: rgba(15, 23, 42, 0.88);
    transition: transform 160ms ease, border-color 160ms ease;
  }

  .mix-card:hover {
    transform: translateY(-3px);
    border-color: rgba(34, 211, 238, 0.45);
  }

  .cover-area {
    aspect-ratio: 1;
    background: linear-gradient(135deg, #10243c, #07111f);
  }

  .mix-cover {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .cover-placeholder {
    display: grid;
    width: 100%;
    height: 100%;
    place-items: center;
    color: #67e8f9;
    font-size: 4rem;
    font-weight: 800;
  }

  .mix-content {
    padding: 1rem;
  }

  .mix-owner {
    color: #67e8f9;
    font-size: 0.85rem;
  }

  .owner-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
  }

  h2 {
    margin: 0.4rem 0;
    color: #f8fafc;
    font-size: 1.2rem;
  }

  .prompt,
  .description {
    color: #a8b3c7;
    line-height: 1.5;
  }

  .description {
    font-size: 0.9rem;
  }

  .mix-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    margin-top: 1rem;
  }

  button {
    min-height: 2.5rem;
    border-radius: 0.65rem;
    cursor: pointer;
  }

  .play-button {
    padding: 0.6rem 1rem;
    border: 0;
    background: #22d3ee;
    color: #07111f;
    font-weight: 700;
  }

  .social-button {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.6rem 0.8rem;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: transparent;
    color: #dbeafe;
  }

  .social-button.active {
    border-color: #22d3ee;
    color: #67e8f9;
    background: rgba(34, 211, 238, 0.1);
  }

  .follow-button {
    min-height: auto;
    padding: 0.35rem 0.7rem;
    border: 1px solid rgba(34, 211, 238, 0.45);
    border-radius: 999px;
    background: transparent;
    color: #67e8f9;
    font-size: 0.78rem;
    font-weight: 700;
  }

  .follow-button.active {
    border-color: rgba(255, 255, 255, 0.15);
    color: #cbd5e1;
  }

  button:focus-visible {
    outline: 2px solid #67e8f9;
    outline-offset: 2px;
  }
</style>
