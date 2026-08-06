<!--
  File: src/lib/components/UserSearchResult.svelte
  Purpose: One row in the "find people" search results list.
  What it does:
  - Links to the user's profile page.
  - Shows a friend-status-aware action: Add Friend, Requested, Respond, or Friends.
-->

<script>
  /**
   * @typedef {import("$lib/services/usersApi.js").UserPublic} UserPublic
   */

  /**
   * @type {{
   *   user: UserPublic,
   *   onSendRequest?: (username: string) => void
   * }}
   */
  let { user, onSendRequest = () => {} } = $props();
</script>

<div class="result card">
  <a class="username" href={`/users/${user.username}`}>{user.username}</a>

  {#if user.friend_status === "none"}
    <button class="secondary-button" onclick={() => onSendRequest(user.username)}>
      Add Friend
    </button>
  {:else if user.friend_status === "pending_outgoing"}
    <span class="status-chip">Requested</span>
  {:else if user.friend_status === "pending_incoming"}
    <a class="status-chip link" href="/friends">Respond to request</a>
  {:else if user.friend_status === "friends"}
    <span class="status-chip friends">Friends</span>
  {/if}
</div>

<style>
  .result {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    padding: 14px 18px;
    animation: fade-rise-in var(--duration-standard) var(--ease-standard) backwards;
  }

  .result:hover {
    border-color: var(--border-soft);
  }

  .username {
    color: var(--text-main);
    font-weight: 900;
    text-decoration: none;
  }

  .username:hover {
    color: var(--accent-2);
  }

  .status-chip {
    color: var(--text-muted);
    font-size: 13px;
    font-weight: 800;
  }

  .status-chip.friends {
    color: var(--success);
  }

  .status-chip.link {
    color: var(--accent-2);
    text-decoration: none;
  }
</style>
