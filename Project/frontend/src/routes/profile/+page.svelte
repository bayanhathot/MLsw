<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';

	import ProfileHero from '$lib/components/profile/ProfileHero.svelte';
	import MusicIdentityDashboard from '$lib/components/profile/MusicIdentityDashboard.svelte';
	import {
		getMyMusicIdentity,
		getMyProfile,
		getPublicProfile,
		updateMusicIdentityPrivacy,
		updateMyProfile
	} from '$lib/services/profileApi.js';
	import { authStore } from '$lib/stores/authStore.js';

	let loaded = $state(false);
	let loading = $state(false);
	let error = $state('');
	let profile = $state(/** @type {Record<string, any> | null} */ (null));
	let publicProfile = $state(/** @type {Record<string, any> | null} */ (null));
	let identity = $state(/** @type {Record<string, any> | null} */ (null));
	let editing = $state(false);
	let privacyBusy = $state(false);
	let displayName = $state('');
	let avatarUrl = $state('');
	let bio = $state('');
	let genres = $state('');
	let periodBusy = $state(false);
	let identityControlsBusy = $derived(privacyBusy || periodBusy);
	let saving = $state(false);
	let saveError = $state('');
	let savedMessage = $state('');

	$effect(() => {
		if ($authStore.status === 'guest') {
			void goto(resolve('/login'));
		} else if ($authStore.status === 'authenticated' && $authStore.user && !loaded) {
			loaded = true;
			void loadProfile($authStore.user.username);
		}
	});

	/** @param {string} username */
	async function loadProfile(username) {
		loading = true;
		error = '';
		try {
			const [profileResult, publicResult, identityResult] = await Promise.all([
				getMyProfile(),
				getPublicProfile(username),
				getMyMusicIdentity()
			]);
			profile = profileResult;
			publicProfile = publicResult;
			identity = identityResult;
			resetProfileForm(profileResult);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not load your profile.';
		} finally {
			loading = false;
		}
	}

	/** @param {Record<string, any>} sourceProfile */
	function resetProfileForm(sourceProfile) {
		displayName = String(sourceProfile.display_name || '');
		avatarUrl = String(sourceProfile.avatar_url || '');
		bio = String(sourceProfile.bio || '');
		genres = Array.isArray(sourceProfile.favorite_genres)
			? sourceProfile.favorite_genres.join(', ')
			: '';
	}

	function toggleEditing() {
		if (!editing && profile) resetProfileForm(profile);
		editing = !editing;
		saveError = '';
		savedMessage = '';
	}

	function cancelEditing() {
		if (profile) resetProfileForm(profile);
		editing = false;
		saveError = '';
		savedMessage = '';
	}

	function retryProfile() {
		const username = $authStore.user?.username;
		if (username) void loadProfile(username);
	}

	/** @param {'private'|'friends'|'public'} nextVisibility */
	async function changePrivacy(nextVisibility) {
		const currentVisibility = identity?.visibility || (identity?.is_public ? 'public' : 'private');
		if (identityControlsBusy || !identity || currentVisibility === nextVisibility) return;
		privacyBusy = true;
		error = '';
		try {
			const updatedIdentity = await updateMusicIdentityPrivacy(nextVisibility);
			const visibility = updatedIdentity?.visibility || nextVisibility;
			// The privacy endpoint returns the all-time identity. Only merge its
			// privacy fields so changing visibility does not reset the time window
			// the listener is currently viewing.
			identity = {
				...identity,
				visibility,
				is_public: visibility === 'public'
			};
			if (publicProfile)
				publicProfile = {
					...publicProfile,
					music_identity_public: visibility === 'public',
					music_identity_visibility: visibility
				};
		} catch (requestError) {
			error =
				requestError instanceof Error
					? requestError.message
					: 'Could not update Music Identity privacy.';
		} finally {
			privacyBusy = false;
		}
	}

	/** @param {'7d'|'30d'|'6m'|'all'} nextPeriod */
	async function changePeriod(nextPeriod) {
		if (identityControlsBusy || identity?.period === nextPeriod) return;
		periodBusy = true;
		error = '';
		try {
			identity = await getMyMusicIdentity(nextPeriod);
		} catch (requestError) {
			error =
				requestError instanceof Error ? requestError.message : 'Could not change analytics period.';
		} finally {
			periodBusy = false;
		}
	}

	/** @param {SubmitEvent} event */
	async function saveProfile(event) {
		event.preventDefault();
		if (saving) return;
		const favoriteGenres = [
			...new Set(
				genres
					.split(',')
					.map((genre) => genre.trim().toLowerCase())
					.filter(Boolean)
			)
		];
		if (favoriteGenres.length > 20) {
			saveError = 'Choose at most 20 music interests.';
			return;
		}
		saving = true;
		saveError = '';
		savedMessage = '';
		try {
			const updatedProfile = await updateMyProfile({
				displayName: displayName.trim() || null,
				avatarUrl: avatarUrl.trim() || null,
				bio: bio.trim() || null,
				favoriteGenres
			});
			profile = updatedProfile;
			publicProfile = {
				...publicProfile,
				display_name: updatedProfile.display_name,
				avatar_url: updatedProfile.avatar_url,
				bio: updatedProfile.bio,
				favorite_genres: updatedProfile.favorite_genres
			};
			savedMessage = 'Profile saved.';
			editing = false;
		} catch (requestError) {
			saveError =
				requestError instanceof Error ? requestError.message : 'Could not save your profile.';
		} finally {
			saving = false;
		}
	}
</script>

<svelte:head><title>Your Music Identity | Cuemix</title></svelte:head>

<main class="profile-page">
	{#if error && !profile}
		<div class="message error" role="alert">
			<span>{error}</span><button type="button" onclick={retryProfile}>Retry</button>
		</div>
	{:else if loading || $authStore.status === 'checking'}
		<div class="loading-state" role="status">
			<span></span><strong>Building your profile view…</strong>
			<p>Loading Music Identity and listening analytics.</p>
		</div>
	{:else if profile && publicProfile && identity}
		<ProfileHero
			username={$authStore.user?.username || publicProfile.username}
			displayName={profile.display_name || ''}
			avatarUrl={profile.avatar_url || ''}
			bio={profile.bio || ''}
			memberSince={publicProfile.member_since}
			isOwner={true}
			onEdit={toggleEditing}
		/>

		{#if savedMessage && !editing}<div class="message success slim" role="status">
				<span>{savedMessage}</span><button type="button" onclick={() => (savedMessage = '')}
					>Dismiss</button
				>
			</div>{/if}

		{#if error}<div class="message error slim" role="alert">
				<span>{error}</span><button type="button" onclick={() => (error = '')}>Dismiss</button>
			</div>{/if}

		{#if editing}
			<section class="settings-panel" aria-labelledby="settings-heading">
				<div class="settings-head">
					<div>
						<p>Profile settings</p>
						<h2 id="settings-heading">Edit how you appear</h2>
					</div>
					<button type="button" class="close-settings" onclick={cancelEditing}>Close</button>
				</div>
				<form class="profile-form" onsubmit={saveProfile}>
					<div class="field-grid">
						<label
							><span>Display name</span><input
								bind:value={displayName}
								maxlength="80"
								disabled={saving}
								autocomplete="name"
								placeholder="Your public display name"
							/></label
						>
						<label
							><span>Avatar URL</span><input
								bind:value={avatarUrl}
								maxlength="1000"
								disabled={saving}
								inputmode="url"
								placeholder="https://…"
							/></label
						>
					</div>
					<label
						><span>Bio</span><textarea
							bind:value={bio}
							maxlength="280"
							disabled={saving}
							placeholder="Tell the community what you listen for."></textarea></label
					>
					<label
						><span>Music interests</span><input
							bind:value={genres}
							disabled={saving}
							placeholder="ambient, house, jazz"
						/><small
							>Genres you say you are into. Your Music Identity is calculated separately from real
							listening.</small
						></label
					>
					<div class="form-actions">
						{#if saveError}<p class="form-error" role="alert">{saveError}</p>{/if}
						<p class="save-status" aria-live="polite">{savedMessage}</p>
						<button class="primary-button" type="submit" disabled={saving}
							>{saving ? 'Saving…' : 'Save profile'}</button
						>
					</div>
				</form>
			</section>
		{/if}

		<MusicIdentityDashboard
			{identity}
			isOwner={true}
			privacyBusy={identityControlsBusy}
			periodBusy={identityControlsBusy}
			onPrivacyChange={changePrivacy}
			onPeriodChange={changePeriod}
		/>

		<div class="secondary-grid">
			<section class="community-card">
				<div class="card-title">
					<div>
						<p>Community footprint</p>
						<h2>Community activity</h2>
					</div>
					<span data-testid="profile-friends-count">{publicProfile.friend_count || 0} friends</span>
				</div>
				<div class="stats-grid">
					<div>
						<strong data-testid="profile-posts-count">{publicProfile.stats.post_count}</strong><span
							>Posts</span
						>
					</div>
					<div>
						<strong data-testid="profile-comments-count">{publicProfile.stats.comment_count}</strong
						><span>Comments received</span>
					</div>
					<div>
						<strong data-testid="profile-upvotes-count"
							>{publicProfile.stats.received_upvotes}</strong
						><span>Upvotes</span>
					</div>
					<div>
						<strong data-testid="profile-downvotes-count"
							>{publicProfile.stats.received_downvotes}</strong
						><span>Downvotes</span>
					</div>
				</div>
			</section>
		</div>
	{/if}
</main>

<style>
	.profile-page {
		width: min(1240px, 100%);
		margin: 0 auto;
		padding: 42px 0 92px;
		display: grid;
		gap: 24px;
	}
	.message {
		display: flex;
		justify-content: space-between;
		gap: 16px;
		padding: 18px;
		border: 1px solid var(--border-soft);
		border-radius: 18px;
		color: var(--text-soft);
		background: rgba(7, 16, 31, 0.78);
	}
	.message.error {
		border-color: rgba(255, 107, 134, 0.36);
		color: #ffb1bf;
	}
	.message.success {
		border-color: rgba(112, 225, 199, 0.3);
		color: #9be7d4;
	}
	.message.slim {
		padding: 12px 15px;
		font-size: 13px;
	}
	.message button,
	.close-settings {
		border: 0;
		background: transparent;
		color: inherit;
		font-weight: 900;
	}
	.loading-state {
		display: grid;
		min-height: 58vh;
		place-content: center;
		justify-items: center;
		text-align: center;
	}
	.loading-state > span {
		width: 52px;
		height: 52px;
		border: 2px solid rgba(125, 183, 255, 0.15);
		border-top-color: var(--accent-2);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}
	.loading-state strong {
		margin-top: 17px;
		font-size: 20px;
	}
	.loading-state p {
		margin: 6px 0 0;
		color: var(--text-muted);
	}
	.settings-panel,
	.community-card {
		padding: 24px;
		border: 1px solid rgba(125, 183, 255, 0.16);
		border-radius: 24px;
		background: linear-gradient(180deg, rgba(9, 18, 34, 0.9), rgba(5, 10, 20, 0.84));
	}
	.settings-head,
	.card-title {
		display: flex;
		justify-content: space-between;
		gap: 16px;
		align-items: flex-start;
	}
	.settings-head p,
	.card-title p {
		margin: 0 0 5px;
		color: #7891b6;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.14em;
		text-transform: uppercase;
	}
	.settings-head h2,
	.card-title h2 {
		margin: 0;
		font-size: 22px;
		letter-spacing: -0.03em;
	}
	.close-settings {
		color: #8fa3bf;
	}
	.profile-form {
		display: grid;
		gap: 15px;
		margin-top: 22px;
	}
	.field-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 14px;
	}
	.profile-form label {
		display: grid;
		gap: 7px;
		color: #aebed3;
		font-size: 12px;
		font-weight: 800;
	}
	.profile-form input,
	.profile-form textarea {
		width: 100%;
		border: 1px solid rgba(125, 183, 255, 0.17);
		border-radius: 13px;
		padding: 12px 13px;
		background: #050b16;
		color: var(--text-main);
	}
	.profile-form textarea {
		min-height: 100px;
		resize: vertical;
	}
	.profile-form small,
	.save-status {
		color: #6f8199;
		font-size: 11px;
	}
	.form-actions {
		display: flex;
		align-items: center;
		gap: 14px;
		min-height: 44px;
	}
	.form-actions .primary-button {
		margin-left: auto;
	}
	.form-error {
		color: #ffb1bf;
		font-size: 12px;
	}
	.secondary-grid {
		display: grid;
		grid-template-columns: 1fr;
		gap: 18px;
	}
	.card-title > span {
		color: #6e819c;
		font-size: 11px;
	}
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 10px;
		margin-top: 20px;
	}
	.stats-grid div {
		display: grid;
		gap: 5px;
		padding: 16px;
		border: 1px solid rgba(255, 255, 255, 0.055);
		border-radius: 16px;
		background: rgba(255, 255, 255, 0.018);
	}
	.stats-grid strong {
		color: #9fc8ff;
		font-size: 27px;
		letter-spacing: -0.04em;
	}
	.stats-grid span {
		color: #71839b;
		font-size: 11px;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (max-width: 680px) {
		.field-grid,
		.stats-grid {
			grid-template-columns: 1fr 1fr;
		}
		.form-actions {
			align-items: stretch;
			flex-direction: column;
		}
		.form-actions .primary-button {
			margin-left: 0;
			align-self: flex-start;
		}
	}
</style>
