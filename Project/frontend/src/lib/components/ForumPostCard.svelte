<script>
	import { onDestroy } from 'svelte';

	import {
		createComment,
		deleteComment,
		deletePost,
		getComments,
		voteComment,
		votePost
	} from '$lib/services/forumApi.js';
	import AttachmentUploader from '$lib/components/AttachmentUploader.svelte';
	import AttachmentMedia from '$lib/components/AttachmentMedia.svelte';
	import { deleteAttachment } from '$lib/services/uploadApi.js';

	/** @typedef {import('$lib/types.js').ForumPost} ForumPost */
	/** @typedef {import('$lib/types.js').ForumComment} ForumComment */
	/** @type {{
	 * post: ForumPost,
	 * authenticated?: boolean,
	 * onUpdate?: (post: ForumPost) => void,
	 * onDelete?: (postId: number) => void,
	 * onRequireLogin?: () => void
	 * }} */
	let {
		post,
		authenticated = false,
		onUpdate = () => {},
		onDelete = () => {},
		onRequireLogin = () => {}
	} = $props();

	let commentsOpen = $state(false);
	let commentsLoaded = $state(false);
	let commentsLoading = $state(false);
	let comments = $state(/** @type {ForumComment[]} */ ([]));
	let commentBody = $state('');
	let commentAnonymous = $state(false);
	let postingComment = $state(false);
	let commentAttachments = $state(/** @type {Record<string, any>[]} */ ([]));
	let error = $state('');
	let postVoteBusy = $state(false);
	let deletingPost = $state(false);
	/** @type {Record<number, boolean>} */
	let commentVoteBusy = $state({});
	/** @type {Record<number, boolean>} */
	let commentDeleteBusy = $state({});
	const commentsController = new AbortController();

	onDestroy(() => {
		commentsController.abort();
		for (const attachment of commentAttachments) {
			void deleteAttachment(Number(attachment.id)).catch(() => {});
		}
	});

	/** @param {string} value */
	function formatDate(value) {
		const date = new Date(value);
		return Number.isNaN(date.getTime())
			? 'Recently'
			: date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
	}

	async function toggleComments() {
		commentsOpen = !commentsOpen;
		if (!commentsOpen || commentsLoaded || commentsLoading) return;
		commentsLoading = true;
		error = '';
		try {
			comments = await getComments(post.id, { signal: commentsController.signal });
			commentsLoaded = true;
		} catch (requestError) {
			if (!commentsController.signal.aborted) {
				error = requestError instanceof Error ? requestError.message : 'Could not load comments.';
			}
		} finally {
			commentsLoading = false;
		}
	}

	/** @param {-1 | 1} value */
	async function handlePostVote(value) {
		if (!authenticated) {
			onRequireLogin();
			return;
		}
		if (postVoteBusy) return;
		postVoteBusy = true;
		error = '';
		try {
			const desired = /** @type {-1 | 0 | 1} */ (post.myVote === value ? 0 : value);
			onUpdate(await votePost(post.id, desired));
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not update your vote.';
		} finally {
			postVoteBusy = false;
		}
	}

	/** @param {SubmitEvent} event */
	async function handleComment(event) {
		event.preventDefault();
		if (!authenticated) {
			onRequireLogin();
			return;
		}
		const body = commentBody.trim();
		if (!body || postingComment) return;
		postingComment = true;
		error = '';
		try {
			const comment = await createComment(post.id, {
				body,
				isAnonymous: commentAnonymous,
				attachmentIds: commentAttachments.map((item) => Number(item.id))
			});
			comments = [...comments, comment];
			commentsLoaded = true;
			commentBody = '';
			commentAnonymous = false;
			commentAttachments = [];
			onUpdate({ ...post, commentCount: post.commentCount + 1 });
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not add the comment.';
		} finally {
			postingComment = false;
		}
	}

	/** @param {Record<string, any>} attachment */
	async function removeCommentAttachment(attachment) {
		try {
			await deleteAttachment(Number(attachment.id));
			commentAttachments = commentAttachments.filter((item) => item.id !== attachment.id);
		} catch (requestError) {
			error =
				requestError instanceof Error ? requestError.message : 'Could not remove the attachment.';
		}
	}

	/** @param {ForumComment} comment @param {-1 | 1} value */
	async function handleCommentVote(comment, value) {
		if (!authenticated) {
			onRequireLogin();
			return;
		}
		if (commentVoteBusy[comment.id]) return;
		commentVoteBusy = { ...commentVoteBusy, [comment.id]: true };
		error = '';
		try {
			const desired = /** @type {-1 | 0 | 1} */ (comment.myVote === value ? 0 : value);
			const updated = await voteComment(comment.id, desired);
			comments = comments.map((item) => (item.id === comment.id ? updated : item));
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not update your vote.';
		} finally {
			const remaining = { ...commentVoteBusy };
			delete remaining[comment.id];
			commentVoteBusy = remaining;
		}
	}

	async function handleDeletePost() {
		if (!post.canDelete || deletingPost) return;
		if (!window.confirm('Delete this post and all of its comments?')) return;
		deletingPost = true;
		error = '';
		try {
			await deletePost(post.id);
			onDelete(post.id);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not delete the post.';
		} finally {
			deletingPost = false;
		}
	}

	/** @param {ForumComment} comment */
	async function handleDeleteComment(comment) {
		if (!comment.canDelete || commentDeleteBusy[comment.id]) return;
		if (!window.confirm('Delete this comment?')) return;
		commentDeleteBusy = { ...commentDeleteBusy, [comment.id]: true };
		error = '';
		try {
			await deleteComment(post.id, comment.id);
			comments = comments.filter((item) => item.id !== comment.id);
			onUpdate({ ...post, commentCount: Math.max(0, post.commentCount - 1) });
		} catch (requestError) {
			error =
				requestError instanceof Error ? requestError.message : 'Could not delete the comment.';
		} finally {
			const remaining = { ...commentDeleteBusy };
			delete remaining[comment.id];
			commentDeleteBusy = remaining;
		}
	}
</script>

<article class="post card">
	<header>
		<div>
			<span class="author">{post.authorUsername}</span>
			<time datetime={post.createdAt}>{formatDate(post.createdAt)}</time>
		</div>
		<div class="header-actions">
			{#if post.isAnonymous}<span class="anonymous-badge">Anonymous post</span>{/if}
			{#if post.canDelete}
				<button
					type="button"
					class="delete-button"
					disabled={deletingPost}
					onclick={handleDeletePost}>{deletingPost ? 'Deleting…' : 'Delete post'}</button
				>
			{/if}
		</div>
	</header>

	<h2>{post.title}</h2>
	<p class="body">{post.body}</p>

	{#if post.attachments.length}
		<div class="attachments" aria-label="Attachments">
			{#each post.attachments as attachment (attachment.id)}
				<AttachmentMedia {attachment} />
			{/each}
		</div>
	{/if}

	<div class="post-actions">
		<div class="votes" aria-label={`Score ${post.score}`}>
			<button
				type="button"
				class:active={post.myVote === 1}
				disabled={postVoteBusy}
				aria-label="Upvote post"
				aria-pressed={post.myVote === 1}
				onclick={() => handlePostVote(1)}>▲</button
			>
			<strong>{post.score}</strong>
			<button
				type="button"
				class:active={post.myVote === -1}
				disabled={postVoteBusy}
				aria-label="Downvote post"
				aria-pressed={post.myVote === -1}
				onclick={() => handlePostVote(-1)}>▼</button
			>
		</div>
		<button
			class="comments-toggle"
			type="button"
			aria-expanded={commentsOpen}
			onclick={toggleComments}
		>
			{post.commentCount}
			{post.commentCount === 1 ? 'comment' : 'comments'}
		</button>
	</div>

	{#if error}<p class="error" role="alert">{error}</p>{/if}

	{#if commentsOpen}
		<section class="comments" aria-label={`Comments on ${post.title}`}>
			{#if commentsLoading}
				<p role="status">Loading comments…</p>
			{:else}
				{#each comments as comment (comment.id)}
					<article class="comment">
						<div class="comment-copy">
							<strong>{comment.authorUsername}</strong>
							<span>{comment.body}</span>
							{#each comment.attachments as attachment (attachment.id)}
								<AttachmentMedia {attachment} />
							{/each}
						</div>
						<div class="votes compact" aria-label={`Comment score ${comment.score}`}>
							<button
								type="button"
								class:active={comment.myVote === 1}
								disabled={commentVoteBusy[comment.id] || commentDeleteBusy[comment.id]}
								aria-label="Upvote comment"
								aria-pressed={comment.myVote === 1}
								onclick={() => handleCommentVote(comment, 1)}>▲</button
							>
							<strong>{comment.score}</strong>
							<button
								type="button"
								class:active={comment.myVote === -1}
								disabled={commentVoteBusy[comment.id] || commentDeleteBusy[comment.id]}
								aria-label="Downvote comment"
								aria-pressed={comment.myVote === -1}
								onclick={() => handleCommentVote(comment, -1)}>▼</button
							>
						</div>
						{#if comment.canDelete}
							<button
								type="button"
								class="delete-button compact-delete"
								disabled={commentDeleteBusy[comment.id]}
								onclick={() => handleDeleteComment(comment)}
								>{commentDeleteBusy[comment.id] ? 'Deleting…' : 'Delete'}</button
							>
						{/if}
					</article>
				{:else}
					<p class="muted">No comments yet.</p>
				{/each}
			{/if}

			<form class="comment-form" onsubmit={handleComment}>
				<label for={`comment-${post.id}`}>Add a comment</label>
				<textarea
					id={`comment-${post.id}`}
					bind:value={commentBody}
					maxlength="2000"
					required
					disabled={postingComment}
					placeholder={authenticated ? 'Join the discussion' : 'Sign in to comment'}></textarea>
				<label class="checkbox"
					><input
						type="checkbox"
						bind:checked={commentAnonymous}
						disabled={!authenticated || postingComment}
					/> Post this comment anonymously</label
				>
				{#if authenticated}
					<AttachmentUploader
						disabled={postingComment || commentAttachments.length >= 4}
						onUploaded={(attachment) => (commentAttachments = [...commentAttachments, attachment])}
					/>
					{#if commentAttachments.length}
						<ul class="staged-attachments">
							{#each commentAttachments as attachment (attachment.id)}
								<li>
									<span>{attachment.filename}</span>
									<button
										type="button"
										disabled={postingComment}
										onclick={() => removeCommentAttachment(attachment)}>Remove</button
									>
								</li>
							{/each}
						</ul>
					{/if}
				{/if}
				<button
					class="primary-button"
					type="submit"
					disabled={postingComment || !commentBody.trim()}
					>{postingComment ? 'Posting…' : 'Post comment'}</button
				>
			</form>
		</section>
	{/if}
</article>

<style>
	.post {
		display: grid;
		gap: 14px;
		padding: 22px;
	}
	.post > * {
		position: relative;
		z-index: 1;
	}
	header,
	header > div,
	.post-actions,
	.votes,
	.comment {
		display: flex;
		align-items: center;
	}
	header {
		justify-content: space-between;
		gap: 12px;
	}
	header > div {
		gap: 10px;
	}
	.header-actions {
		justify-content: flex-end;
		flex-wrap: wrap;
	}
	.author {
		color: var(--text-main);
		font-weight: 900;
	}
	time,
	.muted {
		color: var(--text-muted);
		font-size: 13px;
	}
	.anonymous-badge {
		border-radius: 999px;
		padding: 5px 9px;
		background: rgba(125, 183, 255, 0.1);
		color: var(--accent-2);
		font-size: 12px;
	}
	.delete-button {
		border: 1px solid rgba(255, 107, 134, 0.45);
		border-radius: 999px;
		padding: 6px 10px;
		background: transparent;
		color: #ffb1bf;
		font-size: 12px;
		font-weight: 800;
	}
	.delete-button:disabled {
		opacity: 0.6;
	}
	h2 {
		margin: 2px 0 0;
		font-size: 24px;
	}
	.body {
		margin: 0;
		color: var(--text-soft);
		line-height: 1.65;
		white-space: pre-wrap;
	}
	.attachments {
		margin: 0;
		color: var(--accent-2);
	}
	.post-actions {
		justify-content: space-between;
		gap: 12px;
	}
	.votes {
		gap: 8px;
	}
	.votes button,
	.comments-toggle {
		border: 1px solid var(--border-soft);
		border-radius: 999px;
		background: rgba(125, 183, 255, 0.04);
		color: var(--text-soft);
	}
	.votes button {
		width: 38px;
		height: 38px;
	}
	.votes button.active {
		border-color: var(--accent-2);
		background: rgba(59, 130, 246, 0.2);
		color: white;
	}
	.comments-toggle {
		padding: 9px 13px;
	}
	.error {
		margin: 0;
		color: #ffb1bf;
	}
	.comments {
		display: grid;
		gap: 12px;
		padding-top: 14px;
		border-top: 1px solid var(--border-muted);
	}
	.comment {
		justify-content: space-between;
		gap: 14px;
		padding: 12px;
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.025);
	}
	.comment-copy {
		display: grid;
		gap: 4px;
		color: var(--text-soft);
	}
	.compact {
		flex: 0 0 auto;
	}
	.compact button {
		width: 32px;
		height: 32px;
	}
	.compact-delete {
		flex: 0 0 auto;
	}
	.comment-form {
		display: grid;
		gap: 9px;
		margin-top: 4px;
	}
	.comment-form > label:first-child {
		font-weight: 900;
	}
	textarea {
		min-height: 90px;
		border: 1px solid var(--border-soft);
		border-radius: 12px;
		padding: 12px;
		resize: vertical;
		background: #050b16;
		color: var(--text-main);
	}
	.checkbox {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--text-soft);
		font-size: 14px;
	}
	.checkbox input {
		width: 18px;
		height: 18px;
	}
	.comment-form button {
		justify-self: start;
	}
	.staged-attachments {
		display: grid;
		gap: 5px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.staged-attachments li {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		color: var(--text-soft);
		font-size: 13px;
	}
	.staged-attachments button {
		border: 0;
		background: transparent;
		color: var(--danger);
	}
	@media (max-width: 560px) {
		header,
		.comment {
			align-items: flex-start;
			flex-direction: column;
		}
		.post-actions {
			align-items: stretch;
			flex-direction: column;
		}
		.comments-toggle {
			width: 100%;
		}
	}
</style>
