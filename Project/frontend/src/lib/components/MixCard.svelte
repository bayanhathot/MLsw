<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createPost } from '$lib/services/forumApi.js';
	import { authStore } from '$lib/stores/authStore.js';
	/** @type {{
	 * mix: import('$lib/types.js').Mix,
	 * busyAction?: string,
	 * onPlay?: (mix: import('$lib/types.js').Mix) => void,
	 * onLike?: (mix: import('$lib/types.js').Mix) => void,
	 * onSave?: (mix: import('$lib/types.js').Mix) => void
	 * }} */
	let { mix, busyAction = '', onPlay = () => {}, onLike = () => {}, onSave = () => {} } = $props();

	let hasAudio = $derived(mix.segments.some((segment) => Boolean(segment.audioUrl)));
	let shareOpen = $state(false);
	let shareCaption = $state('');
	let shareVisibility = $state('public');
	let shareBusy = $state(false);
	let shareMessage = $state('');

	async function shareMix() {
		if ($authStore.status !== 'authenticated') {
			void goto(resolve('/login'));
			return;
		}
		if (shareBusy || mix.status !== 'published') return;
		shareBusy = true;
		shareMessage = '';
		try {
			await createPost({
				body: shareCaption.trim() || `Listening to ${mix.title}`,
				kind: 'mix_share',
				visibility: shareVisibility,
				mixId: mix.id
			});
			shareMessage = 'Shared to Community.';
			shareCaption = '';
			setTimeout(() => {
				shareOpen = false;
				shareMessage = '';
			}, 900);
		} catch (error) {
			shareMessage = error instanceof Error ? error.message : 'Could not share this mix.';
		} finally {
			shareBusy = false;
		}
	}
</script>

<article class="mix-card">
	{#if mix.coverUrl}
		<img class="cover" src={mix.coverUrl} alt="" loading="lazy" />
	{:else}
		<div class="cover placeholder" aria-hidden="true">ZX</div>
	{/if}

	<div class="content">
		{#if mix.owner}
			<p class="owner">by @{mix.owner.username}</p>
		{/if}
		<h2>{mix.title}</h2>
		<p class="prompt">{mix.prompt}</p>
		{#if mix.description}
			<p class="description">{mix.description}</p>
		{/if}

		<div class="actions">
			<button class="play" type="button" disabled={!hasAudio} onclick={() => onPlay(mix)}>
				{hasAudio ? 'Play' : 'Unavailable'}
			</button>
			<button
				class:active={mix.isLiked}
				type="button"
				disabled={busyAction === 'like'}
				aria-pressed={mix.isLiked}
				aria-label={`${mix.isLiked ? 'Unlike' : 'Like'} ${mix.title}`}
				onclick={() => onLike(mix)}
			>
				{busyAction === 'like' ? 'Updating…' : mix.isLiked ? 'Liked' : 'Like'}
				<span aria-label={`${mix.likeCount} likes`}>{mix.likeCount}</span>
			</button>
			<button
				class:active={mix.isSaved}
				type="button"
				disabled={busyAction === 'save'}
				aria-pressed={mix.isSaved}
				aria-label={`${mix.isSaved ? 'Remove' : 'Save'} ${mix.title}`}
				onclick={() => onSave(mix)}
			>
				{busyAction === 'save' ? 'Updating…' : mix.isSaved ? 'Saved' : 'Save'}
			</button>
			{#if mix.status === 'published'}<button
					type="button"
					aria-expanded={shareOpen}
					onclick={() => (shareOpen = !shareOpen)}>Share</button
				>{/if}
		</div>
		{#if shareOpen}<div class="share-panel">
				<strong>Share to Community</strong><textarea
					bind:value={shareCaption}
					maxlength="500"
					placeholder="Add a caption…"></textarea>
				<div>
					<select bind:value={shareVisibility}
						><option value="public">Everyone</option><option value="friends">Friends</option
						></select
					><button type="button" disabled={shareBusy} onclick={shareMix}
						>{shareBusy ? 'Sharing…' : 'Share mix'}</button
					>
				</div>
				{#if shareMessage}<p>{shareMessage}</p>{/if}
			</div>{/if}
	</div>
</article>

<style>
	.mix-card {
		overflow: hidden;
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-md);
		background: rgba(7, 16, 31, 0.92);
		box-shadow: var(--shadow-soft);
	}

	.cover {
		display: block;
		width: 100%;
		aspect-ratio: 16 / 10;
		object-fit: cover;
		background: linear-gradient(135deg, #10243c, #07111f);
	}

	.placeholder {
		display: grid;
		place-items: center;
		color: var(--accent-2);
		font-size: 3rem;
		font-weight: 900;
	}

	.content {
		padding: 18px;
	}

	.owner {
		margin: 0;
		color: var(--accent-2);
		font-size: 13px;
		font-weight: 800;
	}

	h2 {
		margin: 7px 0;
		font-size: 20px;
	}

	.prompt,
	.description {
		display: -webkit-box;
		overflow: hidden;
		margin: 8px 0;
		-webkit-box-orient: vertical;
		color: var(--text-soft);
		line-height: 1.5;
	}

	.prompt {
		line-clamp: 2;
		-webkit-line-clamp: 2;
	}

	.description {
		line-clamp: 3;
		-webkit-line-clamp: 3;
		color: var(--text-muted);
		font-size: 14px;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 16px;
	}

	button {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-height: 42px;
		border: 1px solid var(--border-soft);
		border-radius: 999px;
		padding: 9px 13px;
		background: transparent;
		color: var(--text-soft);
		font-weight: 800;
	}

	button.play {
		border: 0;
		background: linear-gradient(135deg, #2f6fee, #6ea9ff);
		color: white;
	}

	button.active {
		border-color: var(--accent-2);
		background: rgba(59, 130, 246, 0.18);
		color: white;
	}

	.share-panel {
		display: grid;
		gap: 8px;
		margin-top: 12px;
		padding: 12px;
		border: 1px solid rgba(125, 183, 255, 0.12);
		border-radius: 14px;
		background: rgba(4, 10, 20, 0.8);
	}
	.share-panel strong {
		font-size: 12px;
		color: #dce9fa;
	}
	.share-panel textarea {
		min-height: 64px;
		border: 1px solid rgba(125, 183, 255, 0.12);
		border-radius: 10px;
		padding: 9px;
		resize: vertical;
		background: #050b16;
		color: white;
	}
	.share-panel > div {
		display: flex;
		gap: 8px;
		justify-content: space-between;
	}
	.share-panel select {
		border: 1px solid rgba(125, 183, 255, 0.12);
		border-radius: 999px;
		padding: 8px 10px;
		background: #07101f;
		color: #9eb4d1;
	}
	.share-panel p {
		margin: 0;
		color: #8fb6ed;
		font-size: 11px;
	}
	button:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}
</style>
