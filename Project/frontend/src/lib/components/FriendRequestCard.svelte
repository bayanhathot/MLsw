<!--
  File: src/lib/components/FriendRequestCard.svelte
  Purpose: One row for a pending incoming or outgoing friend request.
  What it does:
  - Incoming requests: shows Accept / Decline buttons.
  - Outgoing requests: shows a Cancel button.
-->

<script>
  /**
   * @typedef {import("$lib/services/friendsApi.js").FriendRequest} FriendRequest
   */

  /**
   * @type {{
   *   request: FriendRequest,
   *   direction: "incoming" | "outgoing",
   *   onAccept?: (id: number) => void,
   *   onDecline?: (id: number) => void,
   *   onCancel?: (id: number) => void
   * }}
   */
  let {
    request,
    direction,
    onAccept = () => {},
    onDecline = () => {},
    onCancel = () => {}
  } = $props();
</script>

<div class="request card">
  <a class="username" href={`/users/${request.other_user.username}`}>
    {request.other_user.username}
  </a>

  <div class="actions">
    {#if direction === "incoming"}
      <button class="primary-button" onclick={() => onAccept(request.id)}>Accept</button>
      <button class="secondary-button" onclick={() => onDecline(request.id)}>Decline</button>
    {:else}
      <button class="secondary-button" onclick={() => onCancel(request.id)}>Cancel</button>
    {/if}
  </div>
</div>

<style>
  .request {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    padding: 14px 18px;
    animation: fade-rise-in var(--duration-standard) var(--ease-standard) backwards;
  }

  .request:hover {
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

  .actions {
    display: flex;
    gap: 10px;
  }

  .actions button {
    padding: 8px 14px;
    font-size: 13px;
  }
</style>
