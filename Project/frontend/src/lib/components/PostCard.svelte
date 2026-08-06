<!--
  File: src/lib/components/PostCard.svelte

  Purpose:
  One feed entry: a shared AI DJ mix with its description, playback
  controls, and social actions (like/comment/share/delete).

  Signature element - the queue strip:
  Instead of a single generic seek bar, the mix's segment queue is drawn
  as a row of blocks sized proportionally to each track's duration, with
  a thin gap between blocks marking the crossfade point. Each block
  fills as it plays and can be clicked to jump straight to that track -
  the AI DJ's structure (how many tracks, how long each one runs) is
  visible at a glance, not hidden behind one flat progress line.
-->

<script>
  /**
   * @typedef {import("$lib/services/postsApi.js").Post} Post
   * @typedef {import("$lib/services/postsApi.js").Comment} Comment
   */

  import { onDestroy, onMount } from "svelte";

  import { addComment, deleteComment, getComments } from "$lib/services/postsApi.js";
  import { reportPlayEvent } from "$lib/services/playEventsApi.js";
  import EqualizerBars from "$lib/components/EqualizerBars.svelte";
  import { parseUtcDate } from "$lib/utils/dates.js";

  // How often to flush accumulated listening time to the backend while
  // playback continues uninterrupted (also flushed on pause/segment
  // advance/unmount - see below).
  const HEARTBEAT_INTERVAL_MS = 15000;

  /**
   * @type {{
   *   post: Post,
   *   currentUsername?: string | null,
   *   onLike?: (postId: number) => Promise<void>,
   *   onUnlike?: (postId: number) => Promise<void>,
   *   onShare?: (postId: number) => Promise<void>,
   *   onDelete?: (postId: number) => Promise<void>
   * }}
   */
  let {
    post,
    currentUsername = null,
    onLike = async () => {},
    onUnlike = async () => {},
    onShare = async () => {},
    onDelete = async () => {}
  } = $props();

  const segments = $derived(post.mix.segments);
  const totalSeconds = $derived(
    segments.reduce((sum, segment) => sum + (segment.end_second - segment.start_second), 0)
  );

  let currentIndex = $state(0);
  let isPlaying = $state(false);
  let currentTime = $state(0);

  // Purely cosmetic mirror of currentTime, refreshed every animation
  // frame instead of only on the native `timeupdate` event (which fires
  // just a handful of times per second - visibly stepped for a 10px-tall
  // fill bar). Kept separate from currentTime so the play-tracking delta
  // math in handleTimeUpdate below stays untouched and correct.
  let visualTime = $state(0);
  let progressFrameId = null;

  /** @type {HTMLAudioElement | null} */
  let audioElement = $state(null);

  const currentSegment = $derived(segments[currentIndex]);
  const hasNext = $derived(currentIndex < segments.length - 1);
  const hasPrevious = $derived(currentIndex > 0);

  function stepProgressFrame() {
    if (audioElement && !audioElement.paused) {
      visualTime = audioElement.currentTime;
    }

    progressFrameId = requestAnimationFrame(stepProgressFrame);
  }

  onMount(() => {
    progressFrameId = requestAnimationFrame(stepProgressFrame);
  });

  onDestroy(() => {
    if (progressFrameId) {
      cancelAnimationFrame(progressFrameId);
    }
  });

  /**
   * @param {number} index
   */
  function segmentFillPercent(index) {
    if (index < currentIndex) return 100;
    if (index > currentIndex) return 0;

    const segment = segments[index];
    const duration = segment.end_second - segment.start_second;

    if (duration <= 0) return 0;

    const played = visualTime - segment.start_second;

    return Math.max(0, Math.min(100, (played / duration) * 100));
  }

  /**
   * @param {import("$lib/services/postsApi.js").MixSegment} segment
   */
  function segmentWidthPercent(segment) {
    if (totalSeconds <= 0) return 100 / segments.length;

    return ((segment.end_second - segment.start_second) / totalSeconds) * 100;
  }

  // Seconds of real listening time accumulated since the last flush to
  // the backend. Reset to 0 every time it's sent.
  let accumulatedSeconds = $state(0);

  /**
   * @param {"heartbeat" | "pause" | "ended" | "unmount"} eventType
   */
  function flushListenedTime(eventType) {
    const segmentId = currentSegment?.id;
    const seconds = Math.round(accumulatedSeconds);

    accumulatedSeconds = 0;

    if (!segmentId || seconds <= 0) return;

    reportPlayEvent({
      mixId: post.mix.id,
      segmentId,
      secondsListened: seconds,
      eventType,
      postId: post.id
    }).catch(() => {
      // Best-effort - losing one play event isn't worth surfacing an error.
    });
  }

  onMount(() => {
    const interval = setInterval(() => flushListenedTime("heartbeat"), HEARTBEAT_INTERVAL_MS);

    return () => {
      clearInterval(interval);
      flushListenedTime("unmount");
    };
  });

  function goToSegment(index) {
    if (index < 0 || index >= segments.length) return;

    flushListenedTime("ended");
    currentIndex = index;
    currentTime = segments[index].start_second;
    visualTime = segments[index].start_second;
  }

  function togglePlay() {
    isPlaying = !isPlaying;
  }

  // Mirrors the drive-the-audio-element-from-state pattern already used
  // by DJPlayerCard: isPlaying is the single source of truth, this effect
  // just makes the real <audio> element match it (including right after
  // the src swaps to the next segment).
  $effect(() => {
    const _trackSegment = currentIndex;

    if (!audioElement) return;

    if (isPlaying) {
      audioElement.play().catch(() => {
        // Autoplay can be blocked by the browser; the play button stays available.
      });
    } else {
      audioElement.pause();
    }
  });

  function handleLoadedMetadata() {
    if (!audioElement || !currentSegment) return;

    if (currentSegment.start_second > 0) {
      audioElement.currentTime = currentSegment.start_second;
    }

    currentTime = audioElement.currentTime;
    visualTime = audioElement.currentTime;
  }

  function handleTimeUpdate() {
    if (!audioElement || !currentSegment) return;

    const newTime = audioElement.currentTime;
    const delta = newTime - currentTime;

    // Only count forward playback, not seeks/jumps (a jump is a much
    // bigger delta than a normal ~250ms timeupdate tick).
    if (delta > 0 && delta < 2) {
      accumulatedSeconds += delta;
    }

    currentTime = newTime;

    if (currentTime >= currentSegment.end_second) {
      if (hasNext) {
        goToSegment(currentIndex + 1);
      } else {
        flushListenedTime("ended");
        isPlaying = false;
      }
    }
  }

  function handlePause() {
    flushListenedTime("pause");
  }

  let likeBusy = $state(false);
  let likeJustPopped = $state(false);

  async function handleToggleLike() {
    if (likeBusy) return;

    likeBusy = true;

    try {
      if (post.liked_by_me) {
        await onUnlike(post.id);
      } else {
        await onLike(post.id);
        likeJustPopped = true;
        setTimeout(() => {
          likeJustPopped = false;
        }, 400);
      }
    } finally {
      likeBusy = false;
    }
  }

  let shareBusy = $state(false);

  async function handleShare() {
    if (shareBusy) return;

    shareBusy = true;

    try {
      await onShare(post.id);
    } finally {
      shareBusy = false;
    }
  }

  let confirmingDelete = $state(false);

  async function handleDeleteClick() {
    if (!confirmingDelete) {
      confirmingDelete = true;
      return;
    }

    await onDelete(post.id);
  }

  let showComments = $state(false);
  /** @type {Comment[]} */
  let comments = $state([]);
  let commentsLoaded = $state(false);
  let commentsLoading = $state(false);
  let commentsError = $state("");
  let newCommentBody = $state("");
  let postingComment = $state(false);

  const displayedCommentCount = $derived(Math.max(post.comment_count, comments.length));

  async function toggleComments() {
    showComments = !showComments;

    if (showComments && !commentsLoaded) {
      commentsLoading = true;
      commentsError = "";

      try {
        comments = await getComments(post.id);
        commentsLoaded = true;
      } catch (err) {
        commentsError = err instanceof Error ? err.message : "Failed to load comments.";
      } finally {
        commentsLoading = false;
      }
    }
  }

  /**
   * @param {SubmitEvent} event
   */
  async function handleAddComment(event) {
    event.preventDefault();

    const body = newCommentBody.trim();
    if (!body || postingComment) return;

    postingComment = true;

    try {
      const comment = await addComment(post.id, body);
      comments = [...comments, comment];
      newCommentBody = "";
    } catch (err) {
      commentsError = err instanceof Error ? err.message : "Failed to add comment.";
    } finally {
      postingComment = false;
    }
  }

  /**
   * @param {number} commentId
   */
  async function handleDeleteComment(commentId) {
    try {
      await deleteComment(post.id, commentId);
      comments = comments.filter((comment) => comment.id !== commentId);
    } catch (err) {
      commentsError = err instanceof Error ? err.message : "Failed to delete comment.";
    }
  }

  /**
   * @param {string} iso
   */
  function formatRelativeTime(iso) {
    const date = parseUtcDate(iso);
    const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));

    if (seconds < 60) return "just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;

    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
</script>

<article class="post-card card">
  <header class="post-header">
    <a class="author" href={`/users/${post.author_username}`}>{post.author_username}</a>
    <span class="timestamp">{formatRelativeTime(post.created_at)}</span>

    {#if currentUsername === post.author_username}
      <button class="delete-button" onclick={handleDeleteClick}>
        {confirmingDelete ? "Confirm delete" : "Delete"}
      </button>
    {/if}
  </header>

  <p class="description">{post.description}</p>

  <div class="player">
    <div class="now-playing">
      {#if currentSegment?.cover_url}
        <img class="cover" src={currentSegment.cover_url} alt={`Cover for ${currentSegment.title}`} />
      {:else}
        <div class="cover placeholder">ZX</div>
      {/if}

      <div class="track-copy">
        <h3>{currentSegment?.title ?? "Untitled"}</h3>
        <p>{currentSegment?.artist ?? "Unknown artist"}</p>
      </div>

      <EqualizerBars active={isPlaying} size="sm" />

      <div class="transport">
        <button class="transport-button" onclick={() => goToSegment(currentIndex - 1)} disabled={!hasPrevious} aria-label="Previous track">
          ⏮
        </button>
        <button class="play-button" onclick={togglePlay} aria-label="Play or pause mix">
          {isPlaying ? "Ⅱ" : "▶"}
        </button>
        <button class="transport-button" onclick={() => goToSegment(currentIndex + 1)} disabled={!hasNext} aria-label="Next track">
          ⏭
        </button>
      </div>
    </div>

    <div class="queue-strip" role="group" aria-label="Mix track queue">
      {#each segments as segment, index (segment.position)}
        <button
          class="queue-block"
          class:active={index === currentIndex}
          class:playing={index === currentIndex && isPlaying}
          style={`flex-grow: ${segmentWidthPercent(segment)};`}
          onclick={() => goToSegment(index)}
          aria-label={`Jump to ${segment.title}`}
          title={`${segment.title} — ${segment.artist}`}
        >
          <span class="queue-fill" style={`width: ${segmentFillPercent(index)}%;`}></span>
        </button>
      {/each}
    </div>

    {#if currentSegment}
      <!-- svelte-ignore a11y_media_has_caption -->
      <audio
        class="hidden-audio"
        bind:this={audioElement}
        src={currentSegment.audio_url}
        preload="auto"
        onloadedmetadata={handleLoadedMetadata}
        ontimeupdate={handleTimeUpdate}
        onpause={handlePause}
      ></audio>
    {/if}
  </div>

  <div class="actions">
    <button class:active={post.liked_by_me} class="action-button" onclick={handleToggleLike} disabled={likeBusy}>
      <span class="heart" class:pop={likeJustPopped}>{post.liked_by_me ? "♥" : "♡"}</span>
      {post.like_count}
    </button>

    <button class="action-button" onclick={toggleComments}>
      💬 {displayedCommentCount}
    </button>

    <button class="action-button" onclick={handleShare} disabled={shareBusy}>
      ↗ Share {post.share_count}
    </button>
  </div>

  {#if showComments}
    <div class="comments">
      {#if commentsLoading}
        <p class="muted">Loading comments...</p>
      {:else}
        {#if commentsError}
          <p class="error">{commentsError}</p>
        {/if}

        {#each comments as comment (comment.id)}
          <div class="comment">
            <a class="comment-author" href={`/users/${comment.author_username}`}>
              {comment.author_username}
            </a>
            <span class="comment-body">{comment.body}</span>
            {#if currentUsername === comment.author_username}
              <button class="comment-delete" onclick={() => handleDeleteComment(comment.id)} aria-label="Delete comment">
                ×
              </button>
            {/if}
          </div>
        {:else}
          <p class="muted">No comments yet.</p>
        {/each}

        <form class="comment-form" onsubmit={handleAddComment}>
          <input
            bind:value={newCommentBody}
            type="text"
            placeholder="Add a comment"
            aria-label="Add a comment"
          />
          <button class="secondary-button" type="submit" disabled={postingComment || !newCommentBody.trim()}>
            Post
          </button>
        </form>
      {/if}
    </div>
  {/if}
</article>

<style>
  .post-card {
    display: grid;
    gap: 16px;
    padding: 22px 24px;
    animation: fade-rise-in var(--duration-entrance) var(--ease-standard) backwards;
  }

  .post-card:hover {
    border-color: var(--border-soft);
    box-shadow: var(--shadow-soft), 0 0 0 1px rgba(125, 183, 255, 0.08);
  }

  .post-header {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .author {
    color: var(--text-main);
    font-weight: 900;
    text-decoration: none;
  }

  .author:hover {
    color: var(--accent-2);
  }

  .timestamp {
    color: var(--text-muted);
    font-size: 13px;
  }

  .delete-button {
    margin-left: auto;
    border: 1px solid var(--border-muted);
    border-radius: 999px;
    padding: 6px 12px;
    color: var(--danger);
    background: transparent;
    font-size: 12px;
    font-weight: 800;
  }

  .description {
    margin: 0;
    color: var(--text-soft);
  }

  .player {
    display: grid;
    gap: 12px;
    padding: 16px;
    border: 1px solid var(--border-muted);
    border-radius: var(--radius-md);
    background: rgba(255, 255, 255, 0.02);
  }

  .now-playing {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .cover {
    width: 54px;
    height: 54px;
    flex: 0 0 auto;
    border-radius: 12px;
    object-fit: cover;
    border: 1px solid rgba(125, 183, 255, 0.2);
  }

  .cover.placeholder {
    display: grid;
    place-items: center;
    color: white;
    background: linear-gradient(135deg, #264984, #6ea9ff);
    font-weight: 1000;
    letter-spacing: 0.08em;
  }

  .track-copy {
    min-width: 0;
    flex: 1;
  }

  .track-copy h3 {
    margin: 0 0 2px;
    overflow: hidden;
    color: var(--text-main);
    font-size: 15px;
    font-weight: 900;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .track-copy p {
    margin: 0;
    overflow: hidden;
    color: var(--text-muted);
    font-size: 13px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .transport {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 0 0 auto;
  }

  .transport-button {
    width: 34px;
    height: 34px;
    border: 1px solid var(--border-muted);
    border-radius: 999px;
    display: grid;
    place-items: center;
    color: var(--text-soft);
    background: rgba(125, 183, 255, 0.05);
    font-size: 14px;
  }

  .transport-button:hover:not(:disabled) {
    border-color: var(--accent-2);
    color: var(--text-main);
    background: rgba(125, 183, 255, 0.14);
  }

  .transport-button:disabled {
    opacity: 0.35;
    cursor: not-allowed;
  }

  .play-button {
    width: 42px;
    height: 42px;
    border: 1px solid rgba(125, 183, 255, 0.28);
    border-radius: 999px;
    display: grid;
    place-items: center;
    color: white;
    background: linear-gradient(135deg, #1f5edb, #74adff);
    box-shadow: var(--shadow-blue);
    font-size: 16px;
  }

  .play-button:hover {
    box-shadow: var(--shadow-blue), 0 0 24px rgba(59, 130, 246, 0.4);
  }

  .queue-strip {
    display: flex;
    gap: 3px;
    height: 10px;
  }

  .queue-block {
    position: relative;
    overflow: hidden;
    height: 100%;
    min-width: 6px;
    border: none;
    border-radius: 4px;
    background: rgba(125, 183, 255, 0.14);
    padding: 0;
  }

  .queue-block:hover {
    background: rgba(125, 183, 255, 0.22);
  }

  .queue-block.active {
    background: rgba(125, 183, 255, 0.28);
  }

  .queue-block.active:hover {
    background: rgba(125, 183, 255, 0.36);
  }

  .queue-block.playing {
    animation: queue-glow 1.6s ease-in-out infinite;
  }

  @keyframes queue-glow {
    0%,
    100% {
      box-shadow: 0 0 0 rgba(125, 183, 255, 0);
    }
    50% {
      box-shadow: 0 0 10px rgba(125, 183, 255, 0.55);
    }
  }

  .queue-fill {
    position: absolute;
    inset: 0 auto 0 0;
    display: block;
    height: 100%;
    background: linear-gradient(90deg, #2f6fee, #7db7ff);
  }

  .hidden-audio {
    display: none;
  }

  .actions {
    display: flex;
    gap: 10px;
  }

  .action-button {
    border: 1px solid var(--border-muted);
    border-radius: 999px;
    padding: 8px 14px;
    color: var(--text-soft);
    background: rgba(255, 255, 255, 0.025);
    font-size: 13px;
    font-weight: 800;
  }

  .action-button:hover:not(:disabled) {
    border-color: var(--accent-2);
    background: rgba(125, 183, 255, 0.08);
  }

  .action-button.active {
    border-color: var(--danger);
    color: var(--danger);
  }

  .action-button.active:hover:not(:disabled) {
    border-color: var(--danger);
    background: rgba(255, 107, 134, 0.08);
  }

  .action-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .heart {
    display: inline-block;
  }

  .heart.pop {
    animation: pop 0.4s var(--ease-out-back);
  }

  .comments {
    display: grid;
    gap: 10px;
    padding-top: 12px;
    border-top: 1px solid var(--border-muted);
  }

  .comment {
    display: flex;
    align-items: baseline;
    gap: 8px;
    animation: fade-rise-in var(--duration-standard) var(--ease-standard) backwards;
  }

  .comment-author {
    color: var(--text-main);
    font-weight: 800;
    font-size: 13px;
    text-decoration: none;
    flex: 0 0 auto;
  }

  .comment-body {
    color: var(--text-soft);
    font-size: 14px;
  }

  .comment-delete {
    margin-left: auto;
    border: none;
    color: var(--text-muted);
    background: transparent;
    font-size: 16px;
    line-height: 1;
  }

  .comment-form {
    display: flex;
    gap: 10px;
  }

  .comment-form input {
    flex: 1;
    border: 1px solid var(--border-soft);
    border-radius: 999px;
    padding: 9px 14px;
    color: var(--text-main);
    background: rgba(0, 229, 255, 0.045);
    outline: none;
  }

  .muted {
    color: var(--text-muted);
    font-size: 14px;
  }

  .error {
    color: var(--danger);
    font-size: 14px;
  }
</style>
