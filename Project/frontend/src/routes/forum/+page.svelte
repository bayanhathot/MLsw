<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onDestroy, onMount } from 'svelte';

	import ForumPostCard from '$lib/components/ForumPostCard.svelte';
	import AttachmentUploader from '$lib/components/AttachmentUploader.svelte';
	import { createPost, getPosts } from '$lib/services/forumApi.js';
	import { authStore } from '$lib/stores/authStore.js';
	import { deleteAttachment } from '$lib/services/uploadApi.js';

	/** @typedef {import('$lib/types.js').ForumPost} ForumPost */
	const PAGE_SIZE = 10;
	let posts = $state(/** @type {ForumPost[]} */ ([]));
	let loading = $state(true);
	let loadingMore = $state(false);
	let hasMore = $state(true);
	let error = $state('');
	let title = $state('');
	let body = $state('');
	let anonymous = $state(false);
	let posting = $state(false);
	let postAttachments = $state(/** @type {Record<string, any>[]} */ ([]));
	const postsController = new AbortController();

	onMount(() => {
		void loadPosts(postsController.signal, true);
	});

	onDestroy(() => {
		postsController.abort();
		for (const attachment of postAttachments) {
			void deleteAttachment(Number(attachment.id)).catch(() => {});
		}
	});

	/** @param {AbortSignal | undefined} signal @param {boolean} [reset] */
	async function loadPosts(signal, reset = false) {
		if (loadingMore || (!reset && !hasMore)) return;
		if (reset) loading = true;
		else loadingMore = true;
		error = '';
		try {
			const batch = await getPosts({
				limit: PAGE_SIZE,
				offset: reset ? 0 : posts.length,
				signal
			});
			posts = reset
				? batch
				: [
						...posts,
						...batch.filter((candidate) => !posts.some((post) => post.id === candidate.id))
					];
			hasMore = batch.length === PAGE_SIZE;
		} catch (requestError) {
			if (!signal?.aborted) {
				error = requestError instanceof Error ? requestError.message : 'Could not load the forum.';
			}
		} finally {
			if (!signal?.aborted) {
				loading = false;
				loadingMore = false;
			}
		}
	}

	function requireLogin() {
		void goto(resolve('/login'));
	}

	/** @param {Record<string, any>} attachment */
	async function removePostAttachment(attachment) {
		try {
			await deleteAttachment(Number(attachment.id));
			postAttachments = postAttachments.filter((item) => item.id !== attachment.id);
		} catch (requestError) {
			error =
				requestError instanceof Error ? requestError.message : 'Could not remove the attachment.';
		}
	}

	/** @param {SubmitEvent} event */
	async function handleCreatePost(event) {
		event.preventDefault();
		if ($authStore.status !== 'authenticated') {
			requireLogin();
			return;
		}
		const cleanTitle = title.trim();
		const cleanBody = body.trim();
		if (!cleanTitle || !cleanBody || posting) return;
		posting = true;
		error = '';
		try {
			const post = await createPost({
				title: cleanTitle,
				body: cleanBody,
				isAnonymous: anonymous,
				attachmentIds: postAttachments.map((item) => Number(item.id))
			});
			posts = [post, ...posts];
			title = '';
			body = '';
			anonymous = false;
			postAttachments = [];
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not publish the post.';
		} finally {
			posting = false;
		}
	}

	/** @param {ForumPost} updated */
	function updatePost(updated) {
		posts = posts.map((post) => (post.id === updated.id ? updated : post));
	}

	/** @param {number} postId */
	function removePost(postId) {
		posts = posts.filter((post) => post.id !== postId);
	}
</script>

<svelte:head><title>Community forum | Zonix</title></svelte:head>

<main class="forum-page">
	<header class="page-header">
		<p class="eyebrow">Community forum</p>
		<h1>Talk music, focus, and flow.</h1>
		<p>Ask for ideas, compare workflows, and share what helps you stay in the zone.</p>
	</header>

	{#if $authStore.status === 'authenticated'}
		<form class="composer card" onsubmit={handleCreatePost}>
			<h2>Start a discussion</h2>
			<label for="post-title">Title</label>
			<input id="post-title" bind:value={title} maxlength="160" required disabled={posting} />
			<label for="post-body">Post</label>
			<textarea
				id="post-body"
				bind:value={body}
				maxlength="5000"
				required
				disabled={posting}
				placeholder="What would you like to discuss?"></textarea>
			<label class="checkbox"
				><input type="checkbox" bind:checked={anonymous} disabled={posting} /> Post anonymously</label
			>
			<AttachmentUploader
				disabled={posting || postAttachments.length >= 8}
				onUploaded={(attachment) => (postAttachments = [...postAttachments, attachment])}
			/>
			{#if postAttachments.length}
				<ul class="pending-attachments" aria-label="Attachments ready to post">
					{#each postAttachments as attachment (attachment.id)}
						<li>
							<span>{attachment.filename}</span>
							<button
								type="button"
								aria-label={`Remove ${attachment.filename}`}
								disabled={posting}
								onclick={() => removePostAttachment(attachment)}>Remove</button
							>
						</li>
					{/each}
				</ul>
			{/if}
			<button
				class="primary-button"
				type="submit"
				disabled={posting || !title.trim() || !body.trim()}
				>{posting ? 'Publishing…' : 'Publish post'}</button
			>
		</form>
	{:else if $authStore.status === 'guest'}
		<div class="sign-in-card card">
			<p>Reading is public. Sign in to post, comment, or vote.</p>
			<a class="secondary-button" href={resolve('/login')}>Sign in</a>
		</div>
	{/if}

	{#if error}
		<div class="error" role="alert">
			<span>{error}</span>
			<button type="button" onclick={() => void loadPosts(postsController.signal, true)}
				>Retry</button
			>
		</div>
	{/if}

	{#if loading}
		<p class="status" role="status">Loading discussions…</p>
	{:else if posts.length === 0}
		<p class="status">No discussions yet. Be the first to start one.</p>
	{:else}
		<div class="post-list">
			{#each posts as post (post.id)}
				<ForumPostCard
					{post}
					authenticated={$authStore.status === 'authenticated'}
					onUpdate={updatePost}
					onDelete={removePost}
					onRequireLogin={requireLogin}
				/>
			{/each}
		</div>
		{#if hasMore}
			<button
				class="load-more secondary-button"
				type="button"
				disabled={loadingMore}
				onclick={() => void loadPosts(postsController.signal)}
				>{loadingMore ? 'Loading…' : 'Load more discussions'}</button
			>
		{/if}
	{/if}
</main>

<style>
	.forum-page {
		display: grid;
		gap: 22px;
		max-width: 820px;
		margin: 0 auto;
		padding: 48px 0 80px;
	}
	.page-header {
		margin-bottom: 6px;
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
		font-size: clamp(38px, 6vw, 62px);
		line-height: 1;
		letter-spacing: -0.05em;
	}
	.page-header > p:last-child,
	.status {
		color: var(--text-soft);
	}
	.composer {
		display: grid;
		gap: 9px;
		padding: 22px;
	}
	.composer > * {
		position: relative;
		z-index: 1;
	}
	.composer h2 {
		margin: 0 0 6px;
	}
	.composer > label:not(.checkbox) {
		font-weight: 900;
	}
	input,
	textarea {
		width: 100%;
		border: 1px solid var(--border-soft);
		border-radius: 12px;
		padding: 12px;
		background: #050b16;
		color: var(--text-main);
	}
	textarea {
		min-height: 130px;
		resize: vertical;
	}
	.checkbox {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--text-soft);
	}
	.checkbox input {
		width: 18px;
		height: 18px;
	}
	.pending-attachments {
		display: grid;
		gap: 6px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.pending-attachments li {
		display: flex;
		justify-content: space-between;
		gap: 10px;
		color: var(--text-soft);
		font-size: 13px;
	}
	.pending-attachments button {
		border: 0;
		background: transparent;
		color: var(--danger);
	}
	.composer button {
		justify-self: start;
	}
	.sign-in-card {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 20px;
	}
	.sign-in-card > * {
		position: relative;
		z-index: 1;
	}
	.sign-in-card a {
		text-decoration: none;
	}
	.error {
		display: flex;
		justify-content: space-between;
		gap: 14px;
		padding: 16px;
		border: 1px solid rgba(255, 107, 134, 0.45);
		border-radius: 14px;
		color: #ffb1bf;
	}
	.error button {
		border: 0;
		background: transparent;
		color: inherit;
		font-weight: 900;
	}
	.post-list {
		display: grid;
		gap: 18px;
	}
	.load-more {
		justify-self: center;
	}
	@media (max-width: 560px) {
		.forum-page {
			padding-top: 30px;
		}
		.sign-in-card {
			align-items: stretch;
			flex-direction: column;
		}
	}
</style>
