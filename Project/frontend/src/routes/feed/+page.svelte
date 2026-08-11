<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';

	import MixCard from '$lib/components/MixCard.svelte';
	import { playerStore } from '$lib/stores/playerStore.js';
	import { getFeed, likeMix, saveMix, unlikeMix, unsaveMix } from '$lib/services/mixApi.js';
	import { authStore } from '$lib/stores/authStore.js';

	/** @typedef {import('$lib/types.js').Mix} Mix */
	const PAGE_SIZE = 12;
	/** @type {Mix[]} */
	let mixes = $state([]);
	let loading = $state(true);
	let loadingMore = $state(false);
	let hasMore = $state(true);
	let error = $state('');
	/** @type {Record<number, string>} */
	let busyActions = $state({});
	const feedController = new AbortController();

	onMount(() => {
		void loadFeed(feedController.signal, true);
		return () => feedController.abort();
	});

	/** @param {AbortSignal | undefined} signal @param {boolean} [reset] */
	async function loadFeed(signal, reset = false) {
		if (loadingMore || (!reset && !hasMore)) return;
		if (reset) loading = true;
		else loadingMore = true;
		error = '';
		try {
			const batch = await getFeed({
				limit: PAGE_SIZE,
				offset: reset ? 0 : mixes.length,
				signal
			});
			mixes = reset
				? batch
				: [...mixes, ...batch.filter((candidate) => !mixes.some((mix) => mix.id === candidate.id))];
			hasMore = batch.length === PAGE_SIZE;
		} catch (requestError) {
			if (!signal?.aborted) {
				error = requestError instanceof Error ? requestError.message : 'Could not load the feed.';
			}
		} finally {
			if (!signal?.aborted) {
				loading = false;
				loadingMore = false;
			}
		}
	}

	function requireAccount() {
		if ($authStore.status === 'authenticated') {
			return true;
		}
		void goto(resolve('/login'));
		return false;
	}

	/** @param {Mix} mix */
	function playMix(mix) {
		if (!mix.segments.some((segment) => segment.audioUrl)) {
			error = 'This mix has no playable audio.';
			return;
		}
		playerStore.play(mix);
	}

	/** @param {Mix} mix */
	async function toggleLike(mix) {
		if (!requireAccount() || busyActions[mix.id]) {
			return;
		}
		const previous = { isLiked: mix.isLiked, likeCount: mix.likeCount };
		const desired = !mix.isLiked;
		busyActions = { ...busyActions, [mix.id]: 'like' };
		mixes = mixes.map((item) =>
			item.id === mix.id
				? { ...item, isLiked: desired, likeCount: Math.max(0, item.likeCount + (desired ? 1 : -1)) }
				: item
		);

		try {
			const result = /** @type {{ is_liked?: boolean, like_count?: number }} */ (
				await (desired ? likeMix(mix.id) : unlikeMix(mix.id))
			);
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
			const remaining = { ...busyActions };
			delete remaining[mix.id];
			busyActions = remaining;
		}
	}

	/** @param {Mix} mix */
	async function toggleSave(mix) {
		if (!requireAccount() || busyActions[mix.id]) {
			return;
		}
		const previous = mix.isSaved;
		const desired = !previous;
		busyActions = { ...busyActions, [mix.id]: 'save' };
		mixes = mixes.map((item) => (item.id === mix.id ? { ...item, isSaved: desired } : item));

		try {
			await (desired ? saveMix(mix.id) : unsaveMix(mix.id));
		} catch (requestError) {
			mixes = mixes.map((item) => (item.id === mix.id ? { ...item, isSaved: previous } : item));
			error =
				requestError instanceof Error ? requestError.message : 'Could not update your library.';
		} finally {
			const remaining = { ...busyActions };
			delete remaining[mix.id];
			busyActions = remaining;
		}
	}
</script>

<svelte:head><title>Community mixes | Zonix</title></svelte:head>

<main class="feed-page">
	<header>
		<p class="eyebrow">Zonix community</p>
		<h1>Discover mixes</h1>
		<p>Listen to published mixes and keep the ones that fit your flow.</p>
	</header>

	{#if error}
		<div class="message error" role="alert">
			<span>{error}</span>
			<button type="button" onclick={() => void loadFeed(feedController.signal, true)}>Retry</button
			>
		</div>
	{/if}

	{#if loading}
		<p class="message" role="status">Loading community mixes…</p>
	{:else if mixes.length === 0}
		<div class="message empty">
			<p>No mixes have been published yet.</p>
			<a class="secondary-button" href={resolve('/')}>Create a session</a>
		</div>
	{:else}
		<div class="mix-grid">
			{#each mixes as mix (mix.id)}
				<MixCard
					{mix}
					busyAction={busyActions[mix.id]}
					onPlay={playMix}
					onLike={toggleLike}
					onSave={toggleSave}
				/>
			{/each}
		</div>
		{#if hasMore}
			<button
				class="load-more secondary-button"
				type="button"
				disabled={loadingMore}
				onclick={() => void loadFeed(feedController.signal)}
				>{loadingMore ? 'Loading…' : 'Load more mixes'}</button
			>
		{/if}
	{/if}
</main>

<style>
	.feed-page {
		max-width: 1200px;
		margin: 0 auto;
		padding: 48px 0 180px;
	}

	header {
		margin-bottom: 30px;
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
		font-size: clamp(38px, 6vw, 68px);
		letter-spacing: -0.05em;
	}

	header > p:last-child,
	.message {
		color: var(--text-soft);
	}

	.mix-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: 20px;
	}

	.load-more {
		display: block;
		margin: 24px auto 0;
	}

	.message {
		padding: 24px;
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-md);
		background: rgba(7, 16, 31, 0.8);
	}

	.message.error {
		display: flex;
		justify-content: space-between;
		gap: 16px;
		margin-bottom: 20px;
		border-color: rgba(255, 107, 134, 0.45);
		color: #ffb1bf;
	}

	.message button {
		border: 0;
		background: transparent;
		color: inherit;
		font-weight: 800;
	}

	.empty {
		text-align: center;
	}

	.empty a {
		display: inline-block;
		margin-top: 8px;
		text-decoration: none;
	}

	@media (max-width: 700px) {
		.feed-page {
			padding-top: 30px;
		}
	}
</style>
