<script>
	import { parseUtcDate } from '$lib/utils/dates.js';

	/** @type {{ username: string, displayName?: string, avatarUrl?: string, bio?: string, memberSince?: string, isOwner?: boolean, onEdit?: () => void }} */
	let {
		username,
		displayName = '',
		avatarUrl = '',
		bio = '',
		memberSince = '',
		isOwner = false,
		onEdit = () => {}
	} = $props();
	let initials = $derived((displayName || username || 'ZX').slice(0, 2).toUpperCase());

	/** @param {string} value */
	function memberDate(value) {
		const date = parseUtcDate(value);
		return Number.isNaN(date.getTime())
			? ''
			: date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
	}
</script>

<section class="profile-hero">
	<div class="ambient" aria-hidden="true"></div>
	<div class="avatar-shell">
		{#if avatarUrl}<img src={avatarUrl} alt={`${username} profile`} />{:else}<span>{initials}</span
			>{/if}
	</div>
	<div class="profile-copy">
		<p class="eyebrow">{isOwner ? 'Your Zonix profile' : 'Zonix listener'}</p>
		<h1>{displayName || username}</h1>
		<div class="identity-line">
			<strong>@{username}</strong>{#if memberSince}<span
					>Member since {memberDate(memberSince)}</span
				>{/if}
		</div>
		<p class="bio">
			{bio ||
				(isOwner
					? 'Add a bio to make your profile feel like yours.'
					: 'This listener has not added a bio yet.')}
		</p>
	</div>
	{#if isOwner}<button class="secondary-button" type="button" onclick={() => onEdit()}
			>Edit profile</button
		>{/if}
</section>

<style>
	.profile-hero {
		position: relative;
		overflow: hidden;
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		gap: 24px;
		align-items: center;
		padding: 28px;
		border: 1px solid rgba(125, 183, 255, 0.18);
		border-radius: 28px;
		background: linear-gradient(
			120deg,
			rgba(10, 20, 39, 0.96),
			rgba(6, 12, 25, 0.9) 54%,
			rgba(16, 19, 44, 0.88)
		);
		box-shadow: 0 24px 80px rgba(0, 0, 0, 0.34);
	}
	.ambient {
		position: absolute;
		width: 420px;
		height: 420px;
		top: -290px;
		left: 15%;
		border-radius: 50%;
		background: radial-gradient(circle, rgba(80, 124, 255, 0.28), transparent 67%);
	}
	.avatar-shell,
	.profile-copy,
	.profile-hero button {
		position: relative;
		z-index: 1;
	}
	.avatar-shell {
		display: grid;
		width: 92px;
		height: 92px;
		place-items: center;
		overflow: hidden;
		border: 1px solid rgba(154, 183, 255, 0.34);
		border-radius: 28px;
		background: linear-gradient(135deg, #274d9c, #7158d9);
		box-shadow: 0 0 38px rgba(81, 112, 255, 0.2);
		color: white;
		font-size: 27px;
		font-weight: 900;
	}
	.avatar-shell img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.eyebrow {
		margin: 0 0 5px;
		color: #7f9fc9;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.15em;
		text-transform: uppercase;
	}
	h1 {
		margin: 0;
		font-size: clamp(34px, 5vw, 58px);
		letter-spacing: -0.055em;
	}
	.identity-line {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
		margin-top: 6px;
	}
	.identity-line strong {
		color: #9bc5ff;
		font-size: 13px;
	}
	.identity-line span {
		color: #687c97;
		font-size: 12px;
	}
	.bio {
		max-width: 700px;
		margin: 10px 0 0;
		color: #93a3ba;
		font-size: 14px;
		line-height: 1.6;
	}
	@media (max-width: 700px) {
		.profile-hero {
			grid-template-columns: auto 1fr;
			padding: 22px;
		}
		.profile-hero button {
			grid-column: 1/-1;
			justify-self: start;
		}
		.avatar-shell {
			width: 72px;
			height: 72px;
			border-radius: 22px;
		}
	}
	@media (max-width: 480px) {
		.profile-hero {
			grid-template-columns: 1fr;
		}
	}
</style>
