<!--
  File: src/lib/components/PostCardSkeleton.svelte
  Purpose: Loading placeholder shaped like PostCard.svelte, so the feed
  doesn't jump/reflow once real posts arrive.
-->

<script>
  import Skeleton from "./Skeleton.svelte";
</script>

<article class="post-card-skeleton card">
  <header class="row">
    <Skeleton width="90px" height="14px" />
    <Skeleton width="50px" height="12px" />
  </header>

  <Skeleton width="70%" height="14px" />

  <div class="player">
    <div class="now-playing">
      <Skeleton width="54px" height="54px" radius="12px" />
      <div class="copy">
        <Skeleton width="60%" height="13px" />
        <Skeleton width="40%" height="11px" />
      </div>
    </div>
    <Skeleton width="100%" height="10px" radius="4px" />
  </div>

  <div class="row">
    <Skeleton width="60px" height="30px" radius="999px" />
    <Skeleton width="60px" height="30px" radius="999px" />
    <Skeleton width="70px" height="30px" radius="999px" />
  </div>
</article>

<style>
  .post-card-skeleton {
    display: grid;
    gap: 16px;
    padding: 22px 24px;
  }

  .row {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .player {
    display: grid;
    gap: 12px;
    padding: 16px;
    border: 1px solid var(--border-muted);
    border-radius: var(--radius-md);
  }

  .now-playing {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .copy {
    flex: 1;
    display: grid;
    gap: 6px;
  }
</style>
