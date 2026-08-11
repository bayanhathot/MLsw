<script>
	/** @type {{ visibility?: 'private'|'friends'|'public', busy?: boolean, onToggle?: (value: 'private'|'friends'|'public') => void }} */
	let { visibility = 'private', busy = false, onToggle = () => {} } = $props();
	let labels = {
		private: ['Private Music Identity', 'Only you can see your listening analytics.', '⌁'],
		friends: ['Friends can see it', 'Only accepted friends can view your Music Identity.', '◉'],
		public: ['Public Music Identity', 'Anyone can view your Music Identity on your profile.', '◎']
	};
</script>

<div
	class="privacy-control"
	class:public-state={visibility === 'public'}
	class:friends-state={visibility === 'friends'}
>
	<div class="privacy-copy">
		<span class="privacy-icon" aria-hidden="true">{labels[visibility][2]}</span>
		<div>
			<strong>{labels[visibility][0]}</strong>
			<p>{labels[visibility][1]}</p>
		</div>
	</div>
	<div class="segmented" aria-label="Music Identity visibility">
		{#each [['private', 'Only me'], ['friends', 'Friends'], ['public', 'Everyone']] as item (item[0])}
			<button
				type="button"
				class:active={visibility === item[0]}
				disabled={busy}
				onclick={() => onToggle(item[0])}>{item[1]}</button
			>
		{/each}
	</div>
</div>

<style>
	.privacy-control {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 18px;
		padding: 16px 18px;
		border: 1px solid rgba(125, 183, 255, 0.18);
		border-radius: 18px;
		background: rgba(7, 16, 31, 0.72);
	}
	.privacy-control.public-state {
		border-color: rgba(112, 225, 199, 0.28);
		background: linear-gradient(90deg, rgba(42, 181, 153, 0.08), rgba(7, 16, 31, 0.75));
	}
	.privacy-control.friends-state {
		border-color: rgba(130, 126, 255, 0.28);
		background: linear-gradient(90deg, rgba(99, 90, 220, 0.09), rgba(7, 16, 31, 0.75));
	}
	.privacy-copy {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.privacy-icon {
		display: grid;
		width: 38px;
		height: 38px;
		place-items: center;
		border-radius: 12px;
		background: rgba(125, 183, 255, 0.09);
		color: var(--accent-2);
		font-size: 20px;
	}
	strong {
		color: #eef6ff;
		font-size: 14px;
	}
	p {
		margin: 3px 0 0;
		color: #8294ad;
		font-size: 12px;
	}
	.segmented {
		display: flex;
		gap: 4px;
		padding: 4px;
		border: 1px solid rgba(125, 183, 255, 0.12);
		border-radius: 999px;
		background: #050b16;
	}
	.segmented button {
		border: 0;
		border-radius: 999px;
		padding: 8px 11px;
		background: transparent;
		color: #778ba5;
		font-size: 11px;
		font-weight: 900;
	}
	.segmented button.active {
		background: linear-gradient(135deg, rgba(52, 107, 230, 0.45), rgba(111, 82, 214, 0.38));
		color: white;
	}
	.segmented button:disabled {
		opacity: 0.5;
	}
	@media (max-width: 720px) {
		.privacy-control {
			align-items: stretch;
			flex-direction: column;
		}
		.segmented {
			align-self: flex-start;
		}
	}
</style>
