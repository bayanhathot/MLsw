<script>
	/** @type {{
	 * mix: import('$lib/types.js').Mix,
	 * busyAction?: string,
	 * onPlay?: (mix: import('$lib/types.js').Mix) => void,
	 * onLike?: (mix: import('$lib/types.js').Mix) => void,
	 * onSave?: (mix: import('$lib/types.js').Mix) => void
	 * }} */
	let { mix, busyAction = '', onPlay = () => {}, onLike = () => {}, onSave = () => {} } = $props();

	let hasAudio = $derived(mix.segments.some((segment) => Boolean(segment.audioUrl)));
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
		</div>
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

	button:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}
</style>
