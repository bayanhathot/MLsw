<script>
	import { resolve } from '$app/paths';

	let {
		user,
		busy = false,
		onConnect = () => {},
		onCancel = () => {},
		onAccept = () => {},
		onDecline = () => {}
	} = $props();
	let initials = $derived((user.displayName || user.username || 'ZX').slice(0, 2).toUpperCase());
</script>

<article class="user-card">
	<a
		class="avatar"
		href={resolve(`/users/${encodeURIComponent(user.username)}`)}
		aria-label={`Open ${user.username}'s profile`}
	>
		{#if user.avatarUrl}<img src={user.avatarUrl} alt="" />{:else}<span>{initials}</span>{/if}
	</a>
	<div class="copy">
		<a class="name" href={resolve(`/users/${encodeURIComponent(user.username)}`)}
			>{user.displayName || user.username}</a
		>
		<span>@{user.username}</span>
		{#if user.musicInterests?.length}<p>{user.musicInterests.slice(0, 3).join(' · ')}</p>{/if}
		<small
			>{user.friendCount || 0} friends{user.mutualFriendCount
				? ` · ${user.mutualFriendCount} mutual`
				: ''}</small
		>
	</div>
	<div class="actions">
		{#if user.relationshipStatus === 'friends'}
			<a class="action subtle" href={resolve(`/messages?with=${encodeURIComponent(user.username)}`)}
				>Message</a
			>
		{:else if user.relationshipStatus === 'request_sent'}
			<button class="action subtle" type="button" disabled={busy} onclick={() => onCancel(user)}
				>Cancel request</button
			>
		{:else if user.relationshipStatus === 'request_received'}
			<button class="action" type="button" disabled={busy} onclick={() => onAccept(user)}
				>Accept</button
			>
			<button class="action subtle" type="button" disabled={busy} onclick={() => onDecline(user)}
				>Decline</button
			>
		{:else if user.relationshipStatus !== 'self' && user.relationshipStatus !== 'blocked'}
			<button class="action" type="button" disabled={busy} onclick={() => onConnect(user)}
				>Add friend</button
			>
		{/if}
	</div>
</article>

<style>
	.user-card {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		gap: 14px;
		align-items: center;
		padding: 16px;
		border: 1px solid rgba(125, 183, 255, 0.13);
		border-radius: 20px;
		background: linear-gradient(180deg, rgba(10, 20, 38, 0.82), rgba(6, 12, 24, 0.78));
	}
	.avatar {
		display: grid;
		width: 54px;
		height: 54px;
		place-items: center;
		overflow: hidden;
		border-radius: 17px;
		background: linear-gradient(135deg, #315fb7, #735bd7);
		color: white;
		font-weight: 900;
		text-decoration: none;
	}
	.avatar img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.copy {
		display: grid;
		gap: 3px;
		min-width: 0;
	}
	.name {
		overflow: hidden;
		color: #edf5ff;
		font-weight: 900;
		text-decoration: none;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.copy > span,
	.copy small {
		color: #7286a2;
		font-size: 12px;
	}
	.copy p {
		overflow: hidden;
		margin: 2px 0 0;
		color: #9db3cf;
		font-size: 12px;
		text-overflow: ellipsis;
		white-space: nowrap;
		text-transform: capitalize;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 7px;
		justify-content: flex-end;
	}
	.action {
		border: 0;
		border-radius: 999px;
		padding: 9px 12px;
		background: linear-gradient(135deg, #356fe7, #708cff);
		color: white;
		font-size: 12px;
		font-weight: 900;
		text-decoration: none;
	}
	.subtle {
		border: 1px solid rgba(125, 183, 255, 0.16);
		background: rgba(125, 183, 255, 0.05);
		color: #b8d2f5;
	}
	@media (max-width: 600px) {
		.user-card {
			grid-template-columns: auto 1fr;
		}
		.actions {
			grid-column: 1/-1;
			justify-content: flex-start;
		}
	}
</style>
