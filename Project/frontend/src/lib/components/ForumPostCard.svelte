<script>
	import { onDestroy } from 'svelte';
	import { resolve } from '$app/paths';

	import {
		createComment,
		deleteComment,
		deletePost,
		getComments,
		normalizeComment,
		voteComment,
		votePost
	} from '$lib/services/forumApi.js';
	import { subscribe } from '$lib/services/realtimeSocket.js';
	import AttachmentUploader from '$lib/components/AttachmentUploader.svelte';
	import AttachmentMedia from '$lib/components/AttachmentMedia.svelte';
	import { deleteAttachment } from '$lib/services/uploadApi.js';
	import { reportContent } from '$lib/services/socialApi.js';
	import { getMix } from '$lib/services/mixApi.js';
	import { playerStore } from '$lib/stores/playerStore.js';
	import { formatUtcDate } from '$lib/utils/dates.js';

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
	let sharedMixBusy = $state(false);
	/** @type {Record<number, boolean>} */
	let commentVoteBusy = $state({});
	/** @type {Record<number, boolean>} */
	let commentDeleteBusy = $state({});
	const commentsController = new AbortController();
	/** @type {(() => void) | null} */
	let unsubscribePostChannel = null;

	onDestroy(() => {
		commentsController.abort();
		unsubscribeFromPostChannel();
		for (const attachment of commentAttachments) {
			void deleteAttachment(Number(attachment.id)).catch(() => {});
		}
	});

	function unsubscribeFromPostChannel() {
		if (unsubscribePostChannel) {
			unsubscribePostChannel();
			unsubscribePostChannel = null;
		}
	}

	function subscribeToPostChannel() {
		if (unsubscribePostChannel) return;
		unsubscribePostChannel = subscribe(
			`post:${post.id}`,
			(type, data) => handlePostChannelEvent(type, data),
			{
				// No single-post refetch endpoint exists on the frontend yet,
				// so a reconnect only resyncs the comment list, not the post's
				// own score -- an acceptable gap for this rare edge case.
				onResync: () => void refreshComments()
			}
		);
	}

	async function refreshComments() {
		try {
			comments = await getComments(post.id, { signal: commentsController.signal });
			commentsLoaded = true;
		} catch {
			// Best-effort realtime resync; the comment list stays as-is.
		}
	}

	/** @param {string} type @param {unknown} data */
	function handlePostChannelEvent(type, data) {
		const payload = /** @type {Record<string, any>} */ (data || {});
		if (type === 'comment_created') {
			let comment;
			try {
				comment = normalizeComment(payload);
			} catch {
				return;
			}
			if (comments.some((item) => item.id === comment.id)) return;
			comments = [...comments, comment];
			onUpdate({ ...post, commentCount: post.commentCount + 1 });
		} else if (type === 'vote_changed') {
			onUpdate({ ...post, score: Number(payload.score) });
		} else if (type === 'comment_vote_changed') {
			const commentId = Number(payload.comment_id);
			comments = comments.map((item) =>
				item.id === commentId ? { ...item, score: Number(payload.score) } : item
			);
		} else if (type === 'comment_deleted') {
			const commentId = Number(payload.comment_id);
			if (!comments.some((item) => item.id === commentId)) return;
			comments = comments.filter((item) => item.id !== commentId);
			onUpdate({ ...post, commentCount: Math.max(0, post.commentCount - 1) });
		} else if (type === 'post_deleted') {
			// Reuses the same removal path the manual "Delete post" button
			// already triggers, so a post deleted by its author elsewhere
			// disappears from this open thread too instead of erroring on
			// the next interaction with it.
			onDelete(post.id);
		}
	}

	/** @param {string} value */
	function formatDate(value) {
		return formatUtcDate(
			value,
			(date) => date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }),
			'Recently'
		);
	}

	async function toggleComments() {
		commentsOpen = !commentsOpen;
		if (!commentsOpen) {
			unsubscribeFromPostChannel();
			return;
		}
		subscribeToPostChannel();
		if (commentsLoaded || commentsLoading) return;
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

	async function playSharedMix() {
		if (!post.mix || sharedMixBusy) return;
		sharedMixBusy = true;
		error = '';
		try {
			const mix = await getMix(post.mix.id);
			playerStore.play(mix);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not play this mix.';
		} finally {
			sharedMixBusy = false;
		}
	}

	/** @param {ForumComment} comment */
	async function handleReportComment(comment) {
		if (!authenticated) {
			onRequireLogin();
			return;
		}
		const reason = window.prompt('Why are you reporting this comment?');
		if (!reason?.trim()) return;
		try {
			await reportContent('comment', comment.id, reason.trim());
			error = 'Report received. Thank you.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not send report.';
		}
	}

	async function handleReportPost() {
		if (!authenticated) {
			onRequireLogin();
			return;
		}
		const reason = window.prompt('Why are you reporting this post?');
		if (!reason?.trim()) return;
		try {
			await reportContent('post', post.id, reason.trim());
			error = 'Report received. Thank you.';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not send report.';
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
			{#if !post.isAnonymous && post.authorId}
				<a class="author" href={resolve(`/users/${encodeURIComponent(post.authorUsername)}`)}
					>{post.authorUsername}</a
				>
			{:else}
				<span class="author">{post.authorUsername}</span>
			{/if}
			<time datetime={post.createdAt}>{formatDate(post.createdAt)}</time>
		</div>
		<div class="header-actions">
			<span class="kind-badge"
				>{post.kind === 'discussion'
					? 'Discussion'
					: post.kind === 'mix_share'
						? 'Mix share'
						: post.visibility === 'friends'
							? 'Friends'
							: 'Community'}</span
			>
			{#if post.isAnonymous}<span class="anonymous-badge">Anonymous post</span>{/if}
			{#if post.canDelete}
				<button
					type="button"
					class="delete-button"
					disabled={deletingPost}
					onclick={handleDeletePost}>{deletingPost ? 'Deleting…' : 'Delete post'}</button
				>
			{/if}
			{#if !post.canDelete}<button type="button" class="report-button" onclick={handleReportPost}
					>Report</button
				>{/if}
		</div>
	</header>

	{#if post.kind === 'discussion'}<h2>{post.title}</h2>{/if}
	<p class:status-body={post.kind !== 'discussion'} class="body">{post.body}</p>

	{#if post.mix}
		<div class="shared-mix" aria-label={`Shared mix ${post.mix.title}`}>
			{#if post.mix.coverUrl}<img src={post.mix.coverUrl} alt="" />{:else}<div
					class="mix-placeholder"
				>
					ZX
				</div>{/if}
			<div>
				<span>Shared Cuemix mix</span><strong>{post.mix.title}</strong>
				<p>{post.mix.prompt}</p>
				<small>by @{post.mix.ownerUsername} · {post.mix.segmentCount} segments</small>
			</div>
			<button type="button" disabled={sharedMixBusy} onclick={playSharedMix}
				>{sharedMixBusy ? 'Loading…' : '▶ Play'}</button
			>
		</div>
	{/if}

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
				aria-label={post.kind === 'discussion' ? 'Upvote post' : 'Like post'}
				aria-pressed={post.myVote === 1}
				onclick={() => handlePostVote(1)}>{post.kind === 'discussion' ? '▲' : '♥'}</button
			>
			<strong>{post.score}</strong>
			{#if post.kind === 'discussion'}
				<button
					type="button"
					class:active={post.myVote === -1}
					disabled={postVoteBusy}
					aria-label="Downvote post"
					aria-pressed={post.myVote === -1}
					onclick={() => handlePostVote(-1)}>▼</button
				>
			{/if}
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
							{#if !comment.isAnonymous && comment.authorId}
								<a
									class="comment-author"
									href={resolve(`/users/${encodeURIComponent(comment.authorUsername)}`)}
									>{comment.authorUsername}</a
								>
							{:else}
								<strong>{comment.authorUsername}</strong>
							{/if}
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
								aria-label={post.kind === 'discussion' ? 'Upvote comment' : 'Like comment'}
								aria-pressed={comment.myVote === 1}
								onclick={() => handleCommentVote(comment, 1)}
								>{post.kind === 'discussion' ? '▲' : '♥'}</button
							>
							<strong>{comment.score}</strong>
							{#if post.kind === 'discussion'}
								<button
									type="button"
									class:active={comment.myVote === -1}
									disabled={commentVoteBusy[comment.id] || commentDeleteBusy[comment.id]}
									aria-label="Downvote comment"
									aria-pressed={comment.myVote === -1}
									onclick={() => handleCommentVote(comment, -1)}>▼</button
								>
							{/if}
						</div>
						{#if comment.canDelete}
							<button
								type="button"
								class="delete-button compact-delete"
								disabled={commentDeleteBusy[comment.id]}
								onclick={() => handleDeleteComment(comment)}
								>{commentDeleteBusy[comment.id] ? 'Deleting…' : 'Delete'}</button
							>
						{:else}
							<button
								type="button"
								class="report-button compact-report"
								onclick={() => handleReportComment(comment)}>Report</button
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
					placeholder={authenticated
						? post.kind === 'discussion'
							? 'Join the discussion'
							: 'Add a comment'
						: 'Sign in to comment'}></textarea>
				{#if post.kind === 'discussion'}
					<label class="checkbox"
						><input
							type="checkbox"
							bind:checked={commentAnonymous}
							disabled={!authenticated || postingComment}
						/> Post this comment anonymously</label
					>
				{/if}
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
	.author,
	.comment-author {
		color: var(--text-main);
		font-weight: 900;
		text-decoration: none;
	}
	.author:hover,
	.comment-author:hover {
		color: var(--accent-2);
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	time,
	.muted {
		color: var(--text-muted);
		font-size: 13px;
	}
	.kind-badge,
	.anonymous-badge {
		border-radius: 999px;
		padding: 5px 9px;
		background: rgba(125, 183, 255, 0.1);
		color: var(--accent-2);
		font-size: 12px;
	}
	.report-button {
		border: 0;
		background: none;
		color: #60738d;
		font-size: 11px;
		font-weight: 800;
	}
	.compact-report {
		align-self: center;
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
	.status-body {
		font-size: 16px;
		color: #dce8f8;
	}
	.shared-mix {
		display: grid;
		grid-template-columns: 96px minmax(0, 1fr) auto;
		gap: 14px;
		align-items: center;
		padding: 12px;
		border: 1px solid rgba(125, 183, 255, 0.15);
		border-radius: 18px;
		background: linear-gradient(135deg, rgba(42, 87, 180, 0.13), rgba(106, 77, 201, 0.08));
		color: inherit;
	}
	.shared-mix img,
	.mix-placeholder {
		width: 96px;
		height: 78px;
		object-fit: cover;
		border-radius: 13px;
		background: #0d203b;
		display: grid;
		place-items: center;
		color: #9fc7ff;
		font-weight: 900;
	}
	.shared-mix > div:last-of-type {
		display: grid;
		gap: 3px;
		min-width: 0;
	}
	.shared-mix > button {
		border: 0;
		border-radius: 999px;
		padding: 9px 13px;
		background: linear-gradient(135deg, #356fe7, #735bd7);
		color: white;
		font-weight: 900;
	}
	.shared-mix span,
	.shared-mix small {
		color: #748aa8;
		font-size: 11px;
	}
	.shared-mix strong {
		color: #edf5ff;
	}
	.shared-mix p {
		margin: 0;
		overflow: hidden;
		color: #91a5bf;
		font-size: 12px;
		text-overflow: ellipsis;
		white-space: nowrap;
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
