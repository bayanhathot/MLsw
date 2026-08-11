<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';

	import {
		getMyPreferences,
		getMyProfile,
		getUserStats,
		updateMyProfile
	} from '$lib/services/profileApi.js';
	import { authStore } from '$lib/stores/authStore.js';

	let loaded = $state(false);
	let loading = $state(false);
	let error = $state('');
	/** @type {Record<string, any> | null} */
	let profile = $state(null);
	/** @type {{ received_upvotes: number, received_downvotes: number, post_count: number, comment_count: number } | null} */
	let stats = $state(null);
	let preferences = $state(
		/** @type {{ feedback: string, score: number, count: number }[]} */ ([])
	);
	let displayName = $state('');
	let avatarUrl = $state('');
	let bio = $state('');
	let genres = $state('');
	let themePreference = $state(/** @type {'dark' | 'light' | 'system'} */ ('dark'));
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
			const [profileResult, statsResult, preferenceResult] = await Promise.all([
				getMyProfile(),
				getUserStats(username),
				getMyPreferences()
			]);
			profile = profileResult;
			displayName = String(profileResult.display_name || '');
			avatarUrl = String(profileResult.avatar_url || '');
			bio = String(profileResult.bio || '');
			genres = Array.isArray(profileResult.favorite_genres)
				? profileResult.favorite_genres.join(', ')
				: '';
			themePreference = ['dark', 'light', 'system'].includes(profileResult.theme_preference)
				? profileResult.theme_preference
				: 'dark';
			stats = statsResult;
			preferences = Array.isArray(preferenceResult) ? preferenceResult : [];
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not load your profile.';
		} finally {
			loading = false;
		}
	}

	function retryProfile() {
		const username = $authStore.user?.username;
		if (username) void loadProfile(username);
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
			saveError = 'Choose at most 20 favorite genres.';
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
				favoriteGenres,
				themePreference
			});
			profile = updatedProfile;
			displayName = String(updatedProfile.display_name || '');
			avatarUrl = String(updatedProfile.avatar_url || '');
			bio = String(updatedProfile.bio || '');
			genres = Array.isArray(updatedProfile.favorite_genres)
				? updatedProfile.favorite_genres.join(', ')
				: '';
			savedMessage = 'Profile saved.';
		} catch (requestError) {
			saveError =
				requestError instanceof Error ? requestError.message : 'Could not save your profile.';
		} finally {
			saving = false;
		}
	}
</script>

<svelte:head><title>Your profile | Zonix</title></svelte:head>

<main class="profile-page">
	<header>
		<p class="eyebrow">Your account</p>
		<h1>{$authStore.user?.username || 'Profile'}</h1>
		{#if profile?.display_name}<p>{profile.display_name}</p>{/if}
		{#if profile?.bio}<p class="bio">{profile.bio}</p>{/if}
	</header>

	{#if error}
		<div class="message error" role="alert">
			<span>{error}</span>
			{#if $authStore.user}<button type="button" onclick={retryProfile}>Retry</button>{/if}
		</div>
	{:else if loading || $authStore.status === 'checking'}
		<p class="message" role="status">Loading profile…</p>
	{:else if stats}
		<section aria-labelledby="settings-heading">
			<h2 id="settings-heading">Profile settings</h2>
			<form class="profile-form card" onsubmit={saveProfile}>
				<label for="display-name">Display name</label>
				<input
					id="display-name"
					bind:value={displayName}
					maxlength="80"
					disabled={saving}
					autocomplete="name"
				/>
				<label for="avatar-url">Avatar URL</label>
				<input
					id="avatar-url"
					bind:value={avatarUrl}
					maxlength="1000"
					disabled={saving}
					inputmode="url"
					placeholder="https://example.com/avatar.jpg"
				/>
				<label for="profile-bio">Bio</label>
				<textarea id="profile-bio" bind:value={bio} maxlength="280" disabled={saving}></textarea>
				<label for="favorite-genres">Favorite genres</label>
				<input
					id="favorite-genres"
					bind:value={genres}
					disabled={saving}
					placeholder="ambient, house, jazz"
					aria-describedby="genre-help"
				/>
				<small id="genre-help">Separate up to 20 genres with commas.</small>
				<label for="theme-preference">Theme preference</label>
				<select id="theme-preference" bind:value={themePreference} disabled={saving}>
					<option value="dark">Dark</option>
					<option value="light">Light</option>
					<option value="system">Use system setting</option>
				</select>
				{#if saveError}<p class="form-error" role="alert">{saveError}</p>{/if}
				<p class="save-status" aria-live="polite">{savedMessage}</p>
				<button class="primary-button" type="submit" disabled={saving}
					>{saving ? 'Saving…' : 'Save profile'}</button
				>
			</form>
		</section>
		<section aria-labelledby="activity-heading">
			<h2 id="activity-heading">Forum activity</h2>
			<div class="stats-grid">
				<div><strong>{stats.post_count}</strong><span>Posts</span></div>
				<div><strong>{stats.comment_count}</strong><span>Comments</span></div>
				<div><strong>{stats.received_upvotes}</strong><span>Upvotes received</span></div>
				<div><strong>{stats.received_downvotes}</strong><span>Downvotes received</span></div>
			</div>
		</section>
		<section aria-labelledby="preferences-heading">
			<h2 id="preferences-heading">Remembered DJ directions</h2>
			{#if preferences.length}
				<ul class="preferences">
					{#each preferences as preference (preference.feedback)}
						<li>
							<strong>{preference.feedback.replaceAll('_', ' ')}</strong>
							<span>Strength {preference.score} · used {preference.count} times</span>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="bio">Coach the DJ during sessions to build remembered preferences.</p>
			{/if}
		</section>
	{/if}
</main>

<style>
	.profile-page {
		max-width: 820px;
		margin: 0 auto;
		padding: 48px 0 80px;
	}
	.eyebrow {
		margin: 0;
		color: var(--accent-2);
		font-weight: 900;
		letter-spacing: 0.14em;
		text-transform: uppercase;
	}
	h1 {
		margin: 8px 0;
		font-size: clamp(42px, 7vw, 70px);
		letter-spacing: -0.05em;
	}
	.bio,
	header > p {
		color: var(--text-soft);
	}
	section {
		margin-top: 32px;
	}
	.profile-form {
		display: grid;
		gap: 9px;
		padding: 22px;
	}
	.profile-form > * {
		position: relative;
		z-index: 1;
	}
	.profile-form label {
		font-weight: 900;
	}
	.profile-form input,
	.profile-form textarea,
	.profile-form select {
		width: 100%;
		border: 1px solid var(--border-soft);
		border-radius: 12px;
		padding: 11px;
		background: #050b16;
		color: var(--text-main);
	}
	.profile-form textarea {
		min-height: 100px;
		resize: vertical;
	}
	.profile-form small,
	.save-status {
		margin: 0;
		color: var(--text-muted);
	}
	.form-error {
		margin: 0;
		color: #ffb1bf;
	}
	.profile-form button {
		justify-self: start;
	}
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 14px;
	}
	.stats-grid div {
		display: grid;
		gap: 5px;
		padding: 20px;
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-md);
		background: rgba(7, 16, 31, 0.86);
	}
	.stats-grid strong {
		color: var(--accent-2);
		font-size: 32px;
	}
	.stats-grid span {
		color: var(--text-soft);
		font-size: 14px;
	}
	.preferences {
		display: grid;
		gap: 10px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.preferences li {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		padding: 14px;
		border: 1px solid var(--border-soft);
		border-radius: 12px;
		background: rgba(7, 16, 31, 0.86);
		text-transform: capitalize;
	}
	.preferences span {
		color: var(--text-muted);
	}
	.message {
		padding: 18px;
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-md);
		color: var(--text-soft);
	}
	.message.error {
		display: flex;
		justify-content: space-between;
		border-color: rgba(255, 107, 134, 0.45);
		color: #ffb1bf;
	}
	.message button {
		border: 0;
		background: transparent;
		color: inherit;
		font-weight: 900;
	}
	@media (max-width: 680px) {
		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}
	}
</style>
