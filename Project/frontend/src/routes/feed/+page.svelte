<!--
  File: src/routes/feed/+page.svelte
  Purpose: The feed - shared mixes from yourself and your friends.
-->

<script>
  import { onMount } from "svelte";

  import PostCard from "$lib/components/PostCard.svelte";
  import PostCardSkeleton from "$lib/components/PostCardSkeleton.svelte";
  import PostComposer from "$lib/components/PostComposer.svelte";
  import { authStore } from "$lib/stores/authStore.js";
  import { feedStore } from "$lib/stores/feedStore.js";

  let isPosting = $state(false);

  onMount(() => {
    feedStore.load();
  });

  /**
   * @param {{ prompt: string, description: string }} params
   */
  async function handleCreatePost(params) {
    isPosting = true;

    try {
      await feedStore.createPost(params);
    } finally {
      isPosting = false;
    }
  }
</script>

<section class="feed-page">
  <PostComposer {isPosting} onSubmit={handleCreatePost} />

  {#if $feedStore.status === "loading"}
    <div class="post-list">
      <PostCardSkeleton />
      <PostCardSkeleton />
    </div>
  {:else if $feedStore.status === "error"}
    <p class="error">{$feedStore.error}</p>
  {:else if $feedStore.posts.length === 0}
    <div class="card empty-state">
      <p class="eyebrow">Nothing here yet</p>
      <p class="muted">
        Post a mix above, or add friends to start seeing what they're sharing.
      </p>
    </div>
  {:else}
    <div class="post-list">
      {#each $feedStore.posts as post (post.id)}
        <PostCard
          {post}
          currentUsername={$authStore.user?.username ?? null}
          onLike={feedStore.like}
          onUnlike={feedStore.unlike}
          onShare={feedStore.share}
          onDelete={feedStore.remove}
        />
      {/each}
    </div>
  {/if}
</section>

<style>
  .feed-page {
    display: grid;
    gap: 20px;
    max-width: 720px;
    margin: 0 auto;
    padding: 30px 0 60px;
  }

  .post-list {
    display: grid;
    gap: 20px;
  }

  .empty-state {
    padding: 30px;
    text-align: center;
  }

  .eyebrow {
    margin: 0 0 8px;
    color: var(--accent-2);
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }

  .muted {
    color: var(--text-muted);
  }

  .error {
    color: var(--danger);
  }
</style>
