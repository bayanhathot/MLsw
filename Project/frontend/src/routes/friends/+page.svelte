<!--
  File: src/routes/friends/+page.svelte
  Purpose: Manage friends - search for people, respond to requests, view your friend list.
-->

<script>
  import { onMount } from "svelte";

  import FriendRequestCard from "$lib/components/FriendRequestCard.svelte";
  import UserSearchResult from "$lib/components/UserSearchResult.svelte";
  import { friendsStore } from "$lib/stores/friendsStore.js";
  import { searchUsers } from "$lib/services/usersApi.js";

  let searchQuery = $state("");
  /** @type {import("$lib/services/usersApi.js").UserPublic[]} */
  let searchResults = $state([]);
  let isSearching = $state(false);
  let searchError = $state("");

  onMount(() => {
    friendsStore.load();
  });

  /**
   * @param {SubmitEvent} event
   */
  async function handleSearch(event) {
    event.preventDefault();

    searchError = "";

    if (!searchQuery.trim()) {
      searchResults = [];
      return;
    }

    isSearching = true;

    try {
      searchResults = await searchUsers(searchQuery.trim());
    } catch (err) {
      searchError = err instanceof Error ? err.message : "Search failed.";
    } finally {
      isSearching = false;
    }
  }

  /**
   * @param {string} username
   */
  async function handleSendRequest(username) {
    await friendsStore.sendRequest(username);
    searchResults = searchResults.map((result) =>
      result.username === username ? { ...result, friend_status: "pending_outgoing" } : result
    );
  }
</script>

<section class="friends-page">
  <div class="card search-card">
    <p class="eyebrow">Find people</p>
    <form onsubmit={handleSearch}>
      <input
        bind:value={searchQuery}
        type="text"
        placeholder="Search by username"
        aria-label="Search users"
      />
      <button class="primary-button" type="submit" disabled={isSearching}>
        {isSearching ? "Searching..." : "Search"}
      </button>
    </form>

    {#if searchError}
      <p class="error">{searchError}</p>
    {/if}

    {#if searchResults.length > 0}
      <div class="result-list">
        {#each searchResults as result (result.id)}
          <UserSearchResult user={result} onSendRequest={handleSendRequest} />
        {/each}
      </div>
    {/if}
  </div>

  {#if $friendsStore.status === "error"}
    <p class="error">{$friendsStore.error}</p>
  {/if}

  <div class="card section-card">
    <p class="eyebrow">Friend requests ({$friendsStore.incoming.length})</p>

    {#if $friendsStore.incoming.length === 0}
      <p class="muted">No pending requests.</p>
    {:else}
      <div class="result-list">
        {#each $friendsStore.incoming as request (request.id)}
          <FriendRequestCard
            {request}
            direction="incoming"
            onAccept={friendsStore.accept}
            onDecline={friendsStore.decline}
          />
        {/each}
      </div>
    {/if}
  </div>

  <div class="card section-card">
    <p class="eyebrow">Sent requests ({$friendsStore.outgoing.length})</p>

    {#if $friendsStore.outgoing.length === 0}
      <p class="muted">You have not sent any pending requests.</p>
    {:else}
      <div class="result-list">
        {#each $friendsStore.outgoing as request (request.id)}
          <FriendRequestCard {request} direction="outgoing" onCancel={friendsStore.cancel} />
        {/each}
      </div>
    {/if}
  </div>

  <div class="card section-card">
    <p class="eyebrow">Your friends ({$friendsStore.friends.length})</p>

    {#if $friendsStore.friends.length === 0}
      <p class="muted">You have not added any friends yet.</p>
    {:else}
      <div class="result-list">
        {#each $friendsStore.friends as friend (friend.id)}
          <div class="result card">
            <a class="username" href={`/users/${friend.username}`}>{friend.username}</a>
            <button class="secondary-button" onclick={() => friendsStore.remove(friend.username)}>
              Unfriend
            </button>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</section>

<style>
  .friends-page {
    display: grid;
    gap: 20px;
    padding: 30px 0 60px;
  }

  .search-card,
  .section-card {
    padding: 24px;
  }

  .eyebrow {
    margin: 0 0 14px;
    color: var(--accent-2);
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }

  form {
    display: flex;
    gap: 10px;
  }

  input {
    flex: 1;
    border: 1px solid var(--border-soft);
    border-radius: 16px;
    padding: 12px 14px;
    color: var(--text-main);
    background: rgba(0, 229, 255, 0.045);
    outline: none;
  }

  .error {
    color: var(--danger);
  }

  .muted {
    color: var(--text-muted);
  }

  .result-list {
    display: grid;
    gap: 10px;
    margin-top: 16px;
  }

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
</style>
