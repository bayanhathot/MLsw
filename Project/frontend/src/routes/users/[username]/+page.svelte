<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';

	import { playerStore } from '$lib/stores/playerStore.js';
	import MixCard from '$lib/components/MixCard.svelte';
	import ProfileHero from '$lib/components/profile/ProfileHero.svelte';
	import MusicIdentityDashboard from '$lib/components/profile/MusicIdentityDashboard.svelte';
	import UserCard from '$lib/components/UserCard.svelte';
	import {
		getPublicMixes,
		getPublicMusicIdentity,
		getPublicProfile
	} from '$lib/services/profileApi.js';
	import { likeMix, saveMix, unlikeMix, unsaveMix } from '$lib/services/mixApi.js';
	import {
		acceptFriendRequest,
		blockUser,
		cancelFriendRequest,
		declineFriendRequest,
		getFriendRequests,
		getPublicFriends,
		removeFriend,
		reportContent,
		sendFriendRequest,
		unblockUser
	} from '$lib/services/socialApi.js';
	import { authStore } from '$lib/stores/authStore.js';

	let username = $derived(page.params.username || '');
	let trackedUsername = $state('');
	let loading = $state(true);
	let error = $state('');
	let profile = $state(null);
	let publicIdentity = $state(null);
	let mixes = $state([]);
	let friends = $state([]);
	let activeTab = $state('overview');
	let relationshipBusy = $state(false);
	let periodBusy = $state(false);
	let mixBusy = $state({});

	$effect(() => {
		if (username && username !== trackedUsername) {
			trackedUsername = username;
			void load(username);
		}
	});

	async function load(name) {
		loading = true;
		error = '';
		try {
			[profile, publicIdentity, mixes, friends] = await Promise.all([
				getPublicProfile(name),
				getPublicMusicIdentity(name),
				getPublicMixes(name),
				getPublicFriends(name)
			]);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not load this profile.';
		} finally {
			loading = false;
		}
	}

	function requireAccount() {
		if ($authStore.status === 'authenticated') return true;
		void goto(resolve('/login'));
		return false;
	}

	async function toggleLike(mix) {
		if (!requireAccount() || mixBusy[mix.id]) return;
		const desired = !mix.isLiked;
		const previous = { isLiked: mix.isLiked, likeCount: mix.likeCount };
		mixBusy = { ...mixBusy, [mix.id]: 'like' };
		mixes = mixes.map((item) =>
			item.id === mix.id
				? { ...item, isLiked: desired, likeCount: Math.max(0, item.likeCount + (desired ? 1 : -1)) }
				: item
		);
		try {
			const result = await (desired ? likeMix(mix.id) : unlikeMix(mix.id));
			mixes = mixes.map((item) =>
				item.id === mix.id
					? {
							...item,
							isLiked: result.is_liked ?? desired,
							likeCount: result.like_count ?? item.likeCount
						}
					: item
			);
		} catch (requestError) {
			mixes = mixes.map((item) => (item.id === mix.id ? { ...item, ...previous } : item));
			error = requestError instanceof Error ? requestError.message : 'Could not update the like.';
		} finally {
			const next = { ...mixBusy };
			delete next[mix.id];
			mixBusy = next;
		}
	}

	async function toggleSave(mix) {
		if (!requireAccount() || mixBusy[mix.id]) return;
		const desired = !mix.isSaved;
		const previous = mix.isSaved;
		mixBusy = { ...mixBusy, [mix.id]: 'save' };
		mixes = mixes.map((item) => (item.id === mix.id ? { ...item, isSaved: desired } : item));
		try {
			await (desired ? saveMix(mix.id) : unsaveMix(mix.id));
		} catch (requestError) {
			mixes = mixes.map((item) => (item.id === mix.id ? { ...item, isSaved: previous } : item));
			error =
				requestError instanceof Error ? requestError.message : 'Could not update your library.';
		} finally {
			const next = { ...mixBusy };
			delete next[mix.id];
			mixBusy = next;
		}
	}

	async function changePeriod(period) {
		if (periodBusy) return;
		periodBusy = true;
		try {
			publicIdentity = await getPublicMusicIdentity(username, period);
		} catch (requestError) {
			error =
				requestError instanceof Error ? requestError.message : 'Could not change analytics period.';
		} finally {
			periodBusy = false;
		}
	}

	async function connect() {
		if ($authStore.status !== 'authenticated') return goto(resolve('/login'));
		relationshipBusy = true;
		try {
			await sendFriendRequest(username);
			await load(username);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not update friendship.';
		} finally {
			relationshipBusy = false;
		}
	}
	async function cancelRequest() {
		relationshipBusy = true;
		try {
			await cancelFriendRequest(username);
			await load(username);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not cancel request.';
		} finally {
			relationshipBusy = false;
		}
	}
	async function unfriend() {
		if (!window.confirm(`Remove @${username} from your friends?`)) return;
		relationshipBusy = true;
		try {
			await removeFriend(username);
			await load(username);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not remove friend.';
		} finally {
			relationshipBusy = false;
		}
	}
	async function toggleBlock() {
		if ($authStore.status !== 'authenticated') return;
		if (
			!profile?.viewer_has_blocked &&
			!window.confirm(`Block @${username}? They will not be able to friend or message you.`)
		)
			return;
		relationshipBusy = true;
		try {
			await (profile?.viewer_has_blocked ? unblockUser(username) : blockUser(username));
			await load(username);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not update block.';
		} finally {
			relationshipBusy = false;
		}
	}
	async function reportUser() {
		if ($authStore.status !== 'authenticated' || !profile?.id) return goto(resolve('/login'));
		const reason = window.prompt('Why are you reporting this user?');
		if (!reason?.trim()) return;
		try {
			await reportContent('user', profile.id, reason.trim());
			error = 'Report received. Thank you.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not send report.';
		}
	}

	async function respond(accept) {
		relationshipBusy = true;
		try {
			const requests = await getFriendRequests();
			const request = requests.find(
				(item) => item.sender_username === username && item.status === 'pending'
			);
			if (!request) throw new Error('Friend request was not found.');
			await (accept ? acceptFriendRequest(request.id) : declineFriendRequest(request.id));
			await load(username);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not answer request.';
		} finally {
			relationshipBusy = false;
		}
	}
</script>

<svelte:head><title>{profile?.display_name || username || 'Listener'} | Zonix</title></svelte:head>

<main class="public-profile-page">
	{#if loading}<div class="loading-state">
			<span></span><strong>Loading listener profile…</strong>
		</div>
	{:else if error && !profile}<section class="error-card">
			<strong>Profile unavailable</strong>
			<p>{error}</p>
			<a href={resolve('/community')}>Back to Community</a>
		</section>
	{:else if profile}
		<ProfileHero
			username={profile.username}
			displayName={profile.display_name || ''}
			avatarUrl={profile.avatar_url || ''}
			bio={profile.bio || ''}
			memberSince={profile.member_since}
		/>
		{#if error}<div class="error-inline">
				{error}<button type="button" onclick={() => (error = '')}>×</button>
			</div>{/if}

		<section class="social-bar">
			<div class="counts">
				<button type="button" onclick={() => (activeTab = 'friends')}
					><strong>{profile.friend_count || 0}</strong><span>Friends</span></button
				><button type="button" onclick={() => (activeTab = 'mixes')}
					><strong>{profile.published_mix_count || 0}</strong><span>Mixes</span></button
				><button type="button" onclick={() => (activeTab = 'activity')}
					><strong>{profile.stats.post_count || 0}</strong><span>Posts</span></button
				>{#if profile.mutual_friend_count}<span class="mutual"
						>{profile.mutual_friend_count} mutual friends</span
					>{/if}
			</div>
			<div class="relationship-actions">
				{#if profile.relationship_status === 'none'}<button
						class="primary"
						type="button"
						disabled={relationshipBusy}
						onclick={connect}>Add friend</button
					>
				{:else if profile.relationship_status === 'request_sent'}<button
						class="quiet"
						type="button"
						disabled={relationshipBusy}
						onclick={cancelRequest}>Cancel request</button
					>
				{:else if profile.relationship_status === 'request_received'}<button
						class="primary"
						type="button"
						disabled={relationshipBusy}
						onclick={() => respond(true)}>Accept</button
					><button
						class="quiet"
						type="button"
						disabled={relationshipBusy}
						onclick={() => respond(false)}>Decline</button
					>
				{:else if profile.relationship_status === 'friends'}<button
						class="quiet"
						type="button"
						disabled={relationshipBusy}
						onclick={unfriend}>✓ Friends</button
					><a class="primary" href={resolve(`/messages?with=${encodeURIComponent(username)}`)}
						>Message</a
					>{/if}
			</div>
			{#if $authStore.status === 'authenticated' && profile.relationship_status !== 'self'}<div
					class="safety-actions"
				>
					<button type="button" disabled={relationshipBusy} onclick={toggleBlock}
						>{profile.viewer_has_blocked ? 'Unblock' : 'Block'}</button
					><button type="button" onclick={reportUser}>Report</button>
				</div>{/if}
		</section>

		<nav class="profile-tabs" aria-label="Profile sections">
			{#each [['overview', 'Overview'], ['identity', 'Music Identity'], ['mixes', 'Mixes'], ['activity', 'Activity'], ['friends', 'Friends']] as tab (tab[0])}<button
					class:active={activeTab === tab[0]}
					type="button"
					onclick={() => (activeTab = tab[0])}>{tab[1]}</button
				>{/each}
		</nav>

		{#if activeTab === 'overview'}
			<div class="overview-grid">
				<section class="profile-card">
					<p class="eyebrow">Music identity snapshot</p>
					<h2>
						{publicIdentity?.is_public ? 'How they listen' : 'Listening analytics are private'}
					</h2>
					{#if publicIdentity?.is_public && publicIdentity.music_identity}<div class="snapshot">
							<div>
								<span>Top artist</span><strong
									>{publicIdentity.music_identity.summary.top_artist?.name || '—'}</strong
								>
							</div>
							<div>
								<span>Top genre</span><strong
									>{publicIdentity.music_identity.summary.top_genre?.name || '—'}</strong
								>
							</div>
							<div>
								<span>Top vibe</span><strong
									>{publicIdentity.music_identity.summary.top_vibe?.name || '—'}</strong
								>
							</div>
							<div>
								<span>Listening</span><strong
									>{Math.floor(
										(publicIdentity.music_identity.summary.total_listening_seconds || 0) / 3600
									)}h</strong
								>
							</div>
						</div>
						<button class="text-action" type="button" onclick={() => (activeTab = 'identity')}
							>Open Music Identity →</button
						>{:else}<p class="muted">
							This listener shares their profile, but keeps listening behavior limited to their
							chosen audience.
						</p>{/if}
				</section>
				<section class="profile-card">
					<p class="eyebrow">Music interests</p>
					<h2>Genres they're into</h2>
					{#if profile.favorite_genres?.length}<div class="genre-chips">
							{#each profile.favorite_genres as genre (genre)}<span>{genre}</span>{/each}
						</div>{:else}<p class="muted">No music interests listed yet.</p>{/if}
				</section>
			</div>
			<section class="profile-card">
				<div class="section-head">
					<div>
						<p class="eyebrow">Published sound</p>
						<h2>Recent mixes</h2>
					</div>
					<button type="button" onclick={() => (activeTab = 'mixes')}>See all</button>
				</div>
				{#if mixes.length}<div class="mix-grid compact">
						{#each mixes.slice(0, 3) as mix (mix.id)}<MixCard
								{mix}
								onPlay={(item) => playerStore.play(item)}
								onLike={toggleLike}
								onSave={toggleSave}
								busyAction={mixBusy[mix.id] || ''}
							/>{/each}
					</div>{:else}<p class="muted">No public mixes yet.</p>{/if}
			</section>
		{:else if activeTab === 'identity'}
			{#if publicIdentity?.is_public && publicIdentity.music_identity}<MusicIdentityDashboard
					identity={publicIdentity.music_identity}
					{periodBusy}
					onPeriodChange={changePeriod}
				/>{:else}<section class="private-identity">
					<div class="lock">⌁</div>
					<p class="eyebrow">Music Identity</p>
					<h2>This listener keeps their analytics private.</h2>
					<p>They can choose Only me, Friends, or Everyone from their own profile.</p>
				</section>{/if}
		{:else if activeTab === 'mixes'}
			<section class="profile-card">
				<p class="eyebrow">Public mixes</p>
				<h2>{mixes.length} published mixes</h2>
				{#if mixes.length}<div class="mix-grid">
						{#each mixes as mix (mix.id)}<MixCard
								{mix}
								onPlay={(item) => playerStore.play(item)}
								onLike={toggleLike}
								onSave={toggleSave}
								busyAction={mixBusy[mix.id] || ''}
							/>{/each}
					</div>{:else}<p class="muted">Nothing published yet.</p>{/if}
			</section>
		{:else if activeTab === 'friends'}
			<section class="profile-card">
				<p class="eyebrow">Social circle</p>
				<h2>{friends.length} friends</h2>
				{#if friends.length}<div class="friends-grid">
						{#each friends as friend (friend.id)}<UserCard user={friend} />{/each}
					</div>{:else}<p class="muted">No public friend connections yet.</p>{/if}
			</section>
		{:else}
			<div class="overview-grid">
				<section class="profile-card">
					<p class="eyebrow">Community</p>
					<h2>Activity</h2>
					<div class="stats-grid">
						<div><strong>{profile.stats.post_count}</strong><span>Posts</span></div>
						<div><strong>{profile.stats.comment_count}</strong><span>Comments</span></div>
						<div><strong>{profile.stats.received_upvotes}</strong><span>Positive votes</span></div>
						<div><strong>{profile.stats.received_downvotes}</strong><span>Downvotes</span></div>
					</div>
					<a class="text-link" href={resolve('/community')}>Open Community →</a>
				</section>
			</div>
		{/if}
	{/if}
</main>

<style>
	.public-profile-page {
		width: min(1240px, 100%);
		margin: 0 auto;
		padding: 42px 0 140px;
		display: grid;
		gap: 20px;
	}
	.loading-state {
		display: grid;
		min-height: 55vh;
		place-content: center;
		justify-items: center;
		gap: 14px;
	}
	.loading-state span {
		width: 46px;
		height: 46px;
		border: 2px solid rgba(125, 183, 255, 0.14);
		border-top-color: var(--accent-2);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}
	.error-card,
	.private-identity,
	.profile-card,
	.social-bar {
		border: 1px solid rgba(125, 183, 255, 0.16);
		border-radius: 24px;
		background: linear-gradient(180deg, rgba(9, 18, 34, 0.9), rgba(5, 10, 20, 0.84));
	}
	.error-card {
		display: grid;
		min-height: 300px;
		place-content: center;
		padding: 28px;
		text-align: center;
	}
	.error-card a,
	.text-link {
		color: #9cc7ff;
		font-weight: 900;
	}
	.error-inline {
		display: flex;
		justify-content: space-between;
		padding: 12px 15px;
		border: 1px solid rgba(255, 107, 134, 0.3);
		border-radius: 14px;
		color: #ffb1bf;
	}
	.error-inline button {
		border: 0;
		background: none;
		color: inherit;
	}
	.social-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 18px;
		padding: 14px 18px;
	}
	.counts,
	.relationship-actions,
	.safety-actions {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.counts button {
		display: grid;
		gap: 1px;
		border: 0;
		background: none;
		color: white;
		text-align: left;
	}
	.counts button strong {
		font-size: 18px;
	}
	.counts button span,
	.mutual {
		color: #71839d;
		font-size: 10px;
	}
	.mutual {
		margin-left: 8px;
	}
	.safety-actions {
		margin-left: auto;
	}
	.safety-actions button {
		border: 0;
		background: none;
		color: #667990;
		font-size: 10px;
		font-weight: 800;
	}
	.primary,
	.quiet {
		border-radius: 999px;
		padding: 9px 14px;
		font-weight: 900;
		text-decoration: none;
	}
	.primary {
		border: 0;
		background: linear-gradient(135deg, #356fe7, #735bd7);
		color: white;
	}
	.quiet {
		border: 1px solid rgba(125, 183, 255, 0.14);
		background: rgba(125, 183, 255, 0.04);
		color: #9fb6d5;
	}
	.profile-tabs {
		display: flex;
		gap: 4px;
		overflow: auto;
		padding: 5px;
		border: 1px solid rgba(125, 183, 255, 0.1);
		border-radius: 999px;
		background: rgba(7, 16, 31, 0.52);
	}
	.profile-tabs button {
		border: 0;
		border-radius: 999px;
		padding: 9px 14px;
		background: transparent;
		color: #7488a3;
		font-size: 12px;
		font-weight: 900;
		white-space: nowrap;
	}
	.profile-tabs button.active {
		background: rgba(76, 111, 229, 0.2);
		color: white;
	}
	.overview-grid {
		display: grid;
		grid-template-columns: 1.2fr 0.8fr;
		gap: 18px;
	}
	.profile-card {
		padding: 24px;
	}
	.eyebrow {
		margin: 0 0 6px;
		color: #7892b7;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.15em;
		text-transform: uppercase;
	}
	.profile-card h2,
	.private-identity h2 {
		margin: 0;
		letter-spacing: -0.035em;
	}
	.snapshot {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 8px;
		margin-top: 18px;
	}
	.snapshot > div,
	.stats-grid div {
		display: grid;
		gap: 4px;
		padding: 13px;
		border: 1px solid rgba(255, 255, 255, 0.05);
		border-radius: 14px;
		background: rgba(255, 255, 255, 0.018);
	}
	.snapshot span,
	.stats-grid span,
	.muted {
		color: #74869e;
		font-size: 11px;
	}
	.snapshot strong {
		overflow: hidden;
		color: #dce9fa;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.text-action,
	.section-head button {
		margin-top: 14px;
		border: 0;
		background: none;
		color: #9fc8ff;
		font-size: 12px;
		font-weight: 900;
	}
	.genre-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 18px;
	}
	.genre-chips span {
		border: 1px solid rgba(125, 183, 255, 0.16);
		border-radius: 999px;
		padding: 8px 11px;
		background: rgba(125, 183, 255, 0.05);
		color: #a9c6ea;
		font-size: 12px;
		text-transform: capitalize;
	}
	.section-head {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
	}
	.section-head button {
		margin: 0;
	}
	.mix-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: 16px;
		margin-top: 18px;
	}
	.compact {
		grid-template-columns: repeat(3, 1fr);
	}
	.friends-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 10px;
		margin-top: 18px;
	}
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 8px;
		margin: 18px 0;
	}
	.stats-grid strong {
		color: #9ec8ff;
		font-size: 24px;
	}
	.private-identity {
		padding: 50px 34px;
		text-align: center;
	}
	.lock {
		display: grid;
		width: 64px;
		height: 64px;
		place-items: center;
		margin: 0 auto 16px;
		border-radius: 22px;
		background: rgba(125, 183, 255, 0.06);
		color: #9bc6ff;
		font-size: 28px;
	}
	.private-identity > p:last-child {
		color: #8c9db4;
	}
	.text-link {
		display: inline-block;
		margin-top: 16px;
		text-decoration: none;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (max-width: 900px) {
		.overview-grid,
		.compact {
			grid-template-columns: 1fr;
		}
		.snapshot {
			grid-template-columns: repeat(2, 1fr);
		}
		.friends-grid {
			grid-template-columns: 1fr;
		}
	}
	@media (max-width: 620px) {
		.social-bar {
			align-items: flex-start;
			flex-direction: column;
		}
		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}
	}
</style>
