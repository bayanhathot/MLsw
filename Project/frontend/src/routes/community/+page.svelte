<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { onDestroy, onMount } from 'svelte';

	import AttachmentUploader from '$lib/components/AttachmentUploader.svelte';
	import ForumPostCard from '$lib/components/ForumPostCard.svelte';
	import UserCard from '$lib/components/UserCard.svelte';
	import { reconcileById } from '$lib/services/communityState.js';
	import { createPost, getPosts, normalizePost } from '$lib/services/forumApi.js';
	import { onUserEvent, subscribe } from '$lib/services/realtimeSocket.js';
	import {
		acceptFriendRequest,
		cancelFriendRequest,
		discoverUsers,
		declineFriendRequest,
		getFriendRequests,
		getFriends,
		searchUsers,
		sendFriendRequest
	} from '$lib/services/socialApi.js';
	import { deleteAttachment } from '$lib/services/uploadApi.js';
	import { authStore } from '$lib/stores/authStore.js';

	/** @type {[('friends'|'explore'|'discussions'|'people'), string][]} */
	const tabOptions = [
		['friends', 'Friends'],
		['explore', 'Explore'],
		['discussions', 'Discussions'],
		['people', 'People']
	];
	/** @param {string | null} value @returns {value is 'friends'|'explore'|'discussions'|'people'} */
	function isValidTab(value) {
		return tabOptions.some(([key]) => key === value);
	}

	/** @type {'friends'|'explore'|'discussions'|'people'} */
	let activeTab = $state('explore');
	/** @type {import('$lib/types.js').ForumPost[]} */
	let posts = $state([]);
	let loading = $state(true);
	let error = $state('');
	let body = $state('');
	let title = $state('');
	let anonymous = $state(false);
	/** @type {'public'|'friends'} */
	let visibility = $state('public');
	let posting = $state(false);
	/** @type {Record<string, any>[]} */
	let attachments = $state([]);
	let query = $state('');
	/** @type {import('$lib/types.js').SocialUser[]} */
	let people = $state([]);
	/** @type {import('$lib/types.js').SocialUser[]} */
	let friends = $state([]);
	/** @type {import('$lib/types.js').FriendRequestEntry[]} */
	let requests = $state([]);
	/** @type {Record<string, boolean>} */
	let peopleBusy = $state({});
	let searching = $state(false);
	/** @type {ReturnType<typeof setTimeout> | null} */
	let refreshTimer = null;
	/** @type {(() => void)[]} */
	let feedUnsubscribers = [];
	/** @type {(() => void) | null} */
	let unsubscribePrivateFeed = null;
	let initializedFor = $state('');

	onMount(() => {
		const requested = page.url.searchParams.get('tab');
		activeTab = isValidTab(requested) ? requested : 'explore';
	});

	// Community is members-only end to end (see routers/forum.py and
	// routers/social.py, which now require a real session on every read and
	// write) -- same redirect-on-guest pattern as messages/library/profile,
	// gating the initial load too so a signed-out visitor never fires a
	// doomed request instead of just being sent to /login.
	$effect(() => {
		if ($authStore.status === 'guest') {
			void goto(resolve('/login'));
			return;
		}
		const username = $authStore.user?.username || '';
		if ($authStore.status === 'authenticated' && username && initializedFor !== username) {
			initializedFor = username;
			void loadActive();
			subscribeToFeed(activeTab);
			subscribeToPrivateFeed();
		}
	});

	onDestroy(() => {
		if (refreshTimer) clearTimeout(refreshTimer);
		unsubscribeFromFeed();
		unsubscribeFromPrivateFeed();
	});

	/** "feed:{kind}" is keyed by ForumPost.kind (discussion/status/mix_share),
	 * not by this page's tab -- the discussions tab only ever shows that one
	 * kind, while explore/friends show every kind. */
	/** @param {'friends'|'explore'|'discussions'|'people'} mode */
	function feedChannelsForMode(mode) {
		return mode === 'discussions'
			? ['feed:discussion']
			: ['feed:discussion', 'feed:status', 'feed:mix_share'];
	}

	function unsubscribeFromFeed() {
		for (const unsubscribe of feedUnsubscribers) unsubscribe();
		feedUnsubscribers = [];
	}

	function scheduleFeedRefresh() {
		if (refreshTimer) clearTimeout(refreshTimer);
		refreshTimer = setTimeout(() => void loadActive(), 300);
	}

	function unsubscribeFromPrivateFeed() {
		if (unsubscribePrivateFeed) {
			unsubscribePrivateFeed();
			unsubscribePrivateFeed = null;
		}
	}

	/** Friends-only changes arrive only on each authorized user's private
	 * channel and contain no post content. REST applies the current friendship
	 * and blocking rules when this refresh runs. */
	function subscribeToPrivateFeed() {
		unsubscribeFromPrivateFeed();
		unsubscribePrivateFeed = onUserEvent(
			(type) => {
				if (type === 'feed_changed') scheduleFeedRefresh();
			},
			{ onResync: () => void loadActive() }
		);
	}

	/** @param {'friends'|'explore'|'discussions'|'people'} mode */
	function subscribeToFeed(mode) {
		unsubscribeFromFeed();
		if (mode === 'people') return;
		feedUnsubscribers = feedChannelsForMode(mode).map((channel) =>
			subscribe(
				channel,
				(type, data) => {
					if (type === 'post_created') handleLivePostCreated(data, mode);
					else if (type === 'post_deleted') handleLivePostDeleted(data);
					else if (type === 'feed_changed') scheduleFeedRefresh();
				},
				{ onResync: () => void loadActive() }
			)
		);
	}

	/** @param {unknown} raw @param {'friends'|'explore'|'discussions'} mode */
	function handleLivePostCreated(raw, mode) {
		if (mode === 'friends') {
			// Public feed events still need the REST friendship filter in this
			// mode; friends-only changes use the private handler above.
			scheduleFeedRefresh();
			return;
		}
		let post;
		try {
			post = normalizePost(raw);
		} catch {
			return;
		}
		if (post.visibility !== 'public') return;
		posts = [post, ...posts.filter((item) => item.id !== post.id)];
	}

	/** @param {unknown} raw */
	function handleLivePostDeleted(raw) {
		const payload = /** @type {Record<string, any>} */ (raw || {});
		const postId = Number(payload.post_id);
		// Filtering out an id that was never in the list is a harmless
		// no-op, so this needs no per-mode special-casing like creation does.
		posts = posts.filter((item) => item.id !== postId);
	}

	/** @param {'friends'|'explore'|'discussions'|'people'} tab */
	async function switchTab(tab) {
		activeTab = tab;
		error = '';
		subscribeToFeed(tab);
		await goto(resolve(`/community?tab=${tab}`), { replaceState: true, noScroll: true });
		await loadActive();
	}

	async function loadActive() {
		if (activeTab === 'people') return loadPeople();
		loading = true;
		error = '';
		try {
			posts = await getPosts({ mode: activeTab, limit: 30, offset: 0 });
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not load Community.';
		} finally {
			loading = false;
		}
	}

	async function loadPeople() {
		loading = true;
		error = '';
		try {
			if ($authStore.status !== 'authenticated') {
				friends = [];
				requests = [];
				return;
			}
			[friends, requests, people] = await Promise.all([
				getFriends(),
				getFriendRequests(),
				discoverUsers()
			]);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not load people.';
		} finally {
			loading = false;
		}
	}

	async function runSearch() {
		if (!$authStore.user || query.trim().length < 1) return;
		searching = true;
		error = '';
		try {
			people = await searchUsers(query.trim());
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Search failed.';
		} finally {
			searching = false;
		}
	}

	/** @param {SubmitEvent} event */
	async function handlePost(event) {
		event.preventDefault();
		if ($authStore.status !== 'authenticated') return goto(resolve('/login'));
		if (!body.trim() || posting) return;
		posting = true;
		error = '';
		try {
			const discussion = activeTab === 'discussions';
			const post = await createPost({
				title: discussion ? title.trim() : undefined,
				body: body.trim(),
				isAnonymous: discussion ? anonymous : false,
				kind: discussion ? 'discussion' : 'status',
				visibility: activeTab === 'friends' ? 'friends' : visibility,
				attachmentIds: attachments.map((item) => Number(item.id))
			});
			posts = reconcileById(posts, post, 'start').items;
			body = '';
			title = '';
			anonymous = false;
			attachments = [];
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not publish.';
		} finally {
			posting = false;
		}
	}

	/** @param {Record<string, any>} item */
	async function removeAttachment(item) {
		try {
			await deleteAttachment(Number(item.id));
			attachments = attachments.filter((a) => a.id !== item.id);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not remove attachment.';
		}
	}

	/** @param {string} username */
	function requestFor(username) {
		return requests.find((request) => request.other_user?.username === username);
	}

	/** @param {import('$lib/types.js').SocialUser} user */
	async function connect(user) {
		peopleBusy = { ...peopleBusy, [user.username]: true };
		try {
			await sendFriendRequest(user.username);
			user.relationshipStatus = 'request_sent';
			people = [...people];
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not send request.';
		} finally {
			const next = { ...peopleBusy };
			delete next[user.username];
			peopleBusy = next;
		}
	}

	/** @param {import('$lib/types.js').SocialUser} user */
	async function cancel(user) {
		peopleBusy = { ...peopleBusy, [user.username]: true };
		try {
			await cancelFriendRequest(user.username);
			await loadPeople();
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not cancel request.';
		} finally {
			const next = { ...peopleBusy };
			delete next[user.username];
			peopleBusy = next;
		}
	}

	/** @param {import('$lib/types.js').SocialUser} user */
	async function accept(user) {
		const request = requestFor(user.username);
		if (!request) return;
		peopleBusy = { ...peopleBusy, [user.username]: true };
		try {
			await acceptFriendRequest(request.id);
			await loadPeople();
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not accept request.';
		} finally {
			const next = { ...peopleBusy };
			delete next[user.username];
			peopleBusy = next;
		}
	}

	/** @param {import('$lib/types.js').SocialUser} user */
	async function decline(user) {
		const request = requestFor(user.username);
		if (!request) return;
		peopleBusy = { ...peopleBusy, [user.username]: true };
		try {
			await declineFriendRequest(request.id);
			await loadPeople();
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not decline request.';
		} finally {
			const next = { ...peopleBusy };
			delete next[user.username];
			peopleBusy = next;
		}
	}
</script>

<svelte:head><title>Community | Cuemix</title></svelte:head>

{#if $authStore.status !== 'authenticated'}
	<main class="community-page">
		<p class="redirect-notice">
			{$authStore.status === 'checking' ? 'Checking your session…' : 'Redirecting to sign in…'}
		</p>
	</main>
{:else}
	<main class="community-page">
		<header class="hero">
			<div>
				<p class="eyebrow">Music is better together</p>
				<h1>Community</h1>
				<p>
					Share what you are hearing, follow the sound of your friends, and meet listeners through
					music.
				</p>
			</div>
		</header>

		<nav class="tabs" aria-label="Community sections">
			{#each tabOptions as item (item[0])}
				<button
					class:active={activeTab === item[0]}
					type="button"
					onclick={() => switchTab(item[0])}>{item[1]}</button
				>
			{/each}
		</nav>

		{#if error}<div class="notice error" role="alert">{error}</div>{/if}

		{#if activeTab === 'people'}
			<section class="people-layout">
				<div class="people-main">
					<form
						class="search-card"
						onsubmit={(event) => {
							event.preventDefault();
							void runSearch();
						}}
					>
						<div>
							<p class="eyebrow">Find your people</p>
							<h2>Search listeners</h2>
						</div>
						<div class="search-row">
							<input
								bind:value={query}
								placeholder="Search by username or display name"
								autocomplete="off"
							/><button type="submit" disabled={searching || !query.trim()}
								>{searching ? 'Searching…' : 'Search'}</button
							>
						</div>
					</form>
					{#if people.length}<div class="user-list">
							{#each people as user (user.id)}<UserCard
									{user}
									busy={peopleBusy[user.username]}
									onConnect={connect}
									onCancel={cancel}
									onAccept={accept}
									onDecline={decline}
								/>{/each}
						</div>
					{:else if query && !searching}<div class="empty">
							No listeners matched that search.
						</div>{/if}
				</div>
				<aside>
					<section class="side-card">
						<p class="eyebrow">Requests</p>
						<h3>Friend requests</h3>
						{#each requests.filter((r) => r.receiver_username === $authStore.user?.username) as request (request.id)}
							{#if request.other_user}<UserCard
									user={{
										...request.other_user,
										displayName: request.other_user.display_name,
										avatarUrl: request.other_user.avatar_url,
										musicInterests: request.other_user.music_interests,
										friendCount: request.other_user.friend_count,
										mutualFriendCount: request.other_user.mutual_friend_count,
										relationshipStatus: 'request_received'
									}}
									busy={peopleBusy[request.other_user.username]}
									onAccept={accept}
									onDecline={decline}
								/>{/if}
						{:else}<p class="muted">No incoming requests.</p>{/each}
					</section>
					<section class="side-card">
						<p class="eyebrow">Your circle</p>
						<h3>{friends.length} friends</h3>
						<div class="friend-mini">
							{#each friends.slice(0, 5) as friend (friend.id)}<a
									href={resolve(`/users/${encodeURIComponent(friend.username)}`)}
									>{friend.displayName || friend.username}<span>@{friend.username}</span></a
								>{/each}
						</div>
					</section>
				</aside>
			</section>
		{:else}
			<div class="feed-layout">
				<section class="stream">
					{#if $authStore.status === 'authenticated'}
						<form class="composer" onsubmit={handlePost}>
							<div class="composer-heading">
								<div class="composer-avatar">
									{($authStore.user?.username || 'ZX').slice(0, 2).toUpperCase()}
								</div>
								<div>
									<strong
										>{activeTab === 'discussions'
											? 'Start a music discussion'
											: "What's playing?"}</strong
									><span
										>{activeTab === 'friends'
											? 'Visible to friends'
											: activeTab === 'discussions'
												? 'Ask, compare, or debate music'
												: 'Share with the Cuemix community'}</span
									>
								</div>
							</div>
							{#if activeTab === 'discussions'}<input
									bind:value={title}
									maxlength="160"
									required
									placeholder="Discussion title"
								/>{/if}
							<textarea
								bind:value={body}
								maxlength="5000"
								required
								placeholder={activeTab === 'discussions'
									? 'What do you want to discuss?'
									: 'Share a thought, track discovery, or moment…'}></textarea>
							<div class="composer-tools">
								<AttachmentUploader
									disabled={posting || attachments.length >= 8}
									onUploaded={(item) => (attachments = [...attachments, item])}
								/>
								{#if activeTab === 'discussions'}<label
										><input type="checkbox" bind:checked={anonymous} /> Anonymous</label
									>{:else if activeTab === 'explore'}<select bind:value={visibility}
										><option value="public">Everyone</option><option value="friends">Friends</option
										></select
									>{/if}
								<button
									class="post-button"
									type="submit"
									disabled={posting ||
										!body.trim() ||
										(activeTab === 'discussions' && !title.trim())}
									>{posting ? 'Posting…' : 'Post'}</button
								>
							</div>
							{#if attachments.length}<div class="staged">
									{#each attachments as item (item.id)}<span
											>{item.filename}<button type="button" onclick={() => removeAttachment(item)}
												>×</button
											></span
										>{/each}
								</div>{/if}
						</form>
					{:else}<div class="signin-card">
							Sign in to share music with the community. <a href={resolve('/login')}>Sign in</a>
						</div>{/if}

					{#if loading}<div class="empty">Loading the stream…</div>
					{:else if posts.length === 0}<div class="empty">
							{activeTab === 'friends'
								? 'Your friends have not shared anything yet.'
								: 'No posts here yet. Start the conversation.'}
						</div>
					{:else}<div class="post-list">
							{#each posts as post (post.id)}<ForumPostCard
									{post}
									authenticated={$authStore.status === 'authenticated'}
									onUpdate={(updated) =>
										(posts = posts.map((p) => (p.id === updated.id ? updated : p)))}
									onDelete={(id) => (posts = posts.filter((p) => p.id !== id))}
									onRequireLogin={() => goto(resolve('/login'))}
								/>{/each}
						</div>{/if}
				</section>
				<aside class="context-card">
					<p class="eyebrow">Cuemix social loop</p>
					<h3>Connect through sound</h3>
					<p>
						Listen → build your Music Identity → share a mix → friends react → discover more music.
					</p>
					<a href={resolve('/feed')}>Discover mixes →</a>
				</aside>
			</div>
		{/if}
	</main>
{/if}

<style>
	.community-page {
		width: min(1180px, 100%);
		margin: 0 auto;
		padding: 42px 0 110px;
	}
	.redirect-notice {
		display: grid;
		min-height: 40vh;
		place-content: center;
		color: #8fa2bc;
	}
	.hero {
		display: flex;
		justify-content: space-between;
		gap: 24px;
	}
	.eyebrow {
		margin: 0 0 6px;
		color: #7d9cc7;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.15em;
		text-transform: uppercase;
	}
	h1 {
		margin: 0;
		font-size: clamp(42px, 7vw, 72px);
		letter-spacing: -0.055em;
	}
	.hero p:last-child {
		max-width: 720px;
		color: #8c9db4;
		line-height: 1.7;
	}
	.tabs {
		display: flex;
		gap: 8px;
		margin: 26px 0;
	}
	.tabs button {
		border: 1px solid rgba(125, 183, 255, 0.14);
		border-radius: 999px;
		padding: 10px 16px;
		background: rgba(125, 183, 255, 0.04);
		color: #8fa4c0;
		font-weight: 900;
	}
	.tabs button.active {
		border-color: rgba(115, 152, 255, 0.45);
		background: linear-gradient(135deg, rgba(49, 101, 225, 0.28), rgba(116, 86, 218, 0.2));
		color: white;
	}
	.notice,
	.empty,
	.signin-card {
		padding: 18px;
		border: 1px solid rgba(125, 183, 255, 0.14);
		border-radius: 18px;
		background: rgba(7, 15, 29, 0.72);
		color: #8799b1;
	}
	.error {
		border-color: rgba(255, 105, 135, 0.35);
		color: #ffb2c0;
	}
	.feed-layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 300px;
		gap: 22px;
		align-items: start;
	}
	.stream,
	.post-list {
		display: grid;
		gap: 16px;
	}
	.composer,
	.search-card,
	.side-card,
	.context-card {
		padding: 20px;
		border: 1px solid rgba(125, 183, 255, 0.15);
		border-radius: 24px;
		background: linear-gradient(180deg, rgba(9, 18, 34, 0.9), rgba(5, 10, 20, 0.84));
	}
	.composer {
		display: grid;
		gap: 12px;
	}
	.composer-heading {
		display: flex;
		gap: 12px;
		align-items: center;
	}
	.composer-heading > div:last-child {
		display: grid;
		gap: 2px;
	}
	.composer-heading span {
		color: #74879f;
		font-size: 12px;
	}
	.composer-avatar {
		display: grid;
		width: 42px;
		height: 42px;
		place-items: center;
		border-radius: 14px;
		background: linear-gradient(135deg, #315fb7, #705bd9);
		font-size: 12px;
		font-weight: 900;
	}
	.composer input,
	.composer textarea,
	.search-card input,
	.composer select {
		width: 100%;
		border: 1px solid rgba(125, 183, 255, 0.14);
		border-radius: 14px;
		padding: 12px;
		background: #050b16;
		color: white;
	}
	.composer textarea {
		min-height: 105px;
		resize: vertical;
	}
	.composer-tools {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}
	.composer-tools label {
		display: flex;
		gap: 7px;
		align-items: center;
		color: #8da0b9;
		font-size: 12px;
	}
	.composer-tools label input {
		width: auto;
	}
	.composer-tools select {
		width: auto;
	}
	.post-button,
	.search-row button {
		margin-left: auto;
		border: 0;
		border-radius: 999px;
		padding: 10px 17px;
		background: linear-gradient(135deg, #356fe7, #735bd7);
		color: white;
		font-weight: 900;
	}
	.staged {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.staged span {
		padding: 6px 9px;
		border-radius: 999px;
		background: rgba(125, 183, 255, 0.08);
		color: #9cb5d5;
		font-size: 11px;
	}
	.staged button {
		border: 0;
		background: none;
		color: #ff9cad;
	}
	.context-card {
		position: sticky;
		top: 24px;
	}
	.context-card h3,
	.side-card h3,
	.search-card h2 {
		margin: 0;
	}
	.context-card p {
		color: #8395ad;
		line-height: 1.6;
	}
	.context-card a,
	.signin-card a {
		color: #9fc9ff;
		font-weight: 900;
	}
	.people-layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 360px;
		gap: 22px;
		align-items: start;
	}
	.people-main,
	.user-list,
	aside {
		display: grid;
		gap: 14px;
	}
	.search-card {
		display: grid;
		gap: 14px;
	}
	.search-row {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 10px;
	}
	.search-row button {
		margin: 0;
	}
	.friend-mini {
		display: grid;
		gap: 7px;
		margin-top: 12px;
	}
	.friend-mini a {
		display: flex;
		justify-content: space-between;
		gap: 10px;
		color: #dbe9ff;
		text-decoration: none;
	}
	.friend-mini span,
	.muted {
		color: #6f829c;
		font-size: 12px;
	}
	@media (max-width: 900px) {
		.feed-layout,
		.people-layout {
			grid-template-columns: 1fr;
		}
		.context-card {
			position: static;
		}
	}
	@media (max-width: 600px) {
		.tabs {
			overflow: auto;
		}
		.search-row {
			grid-template-columns: 1fr;
		}
		.composer-tools {
			align-items: stretch;
		}
		.post-button {
			margin-left: 0;
		}
	}
</style>
