<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onDestroy } from 'svelte';

	import { createMix, getLibrary, publishMix, unsaveMix, updateMix } from '$lib/services/mixApi.js';
	import { authStore } from '$lib/stores/authStore.js';
	import { playerStore } from '$lib/stores/playerStore.js';

	/** @typedef {import('$lib/types.js').Mix} Mix */
	/** @type {'owned' | 'saved'} */
	let activeTab = $state('owned');
	/** @type {Mix[]} */
	let owned = $state([]);
	/** @type {Mix[]} */
	let saved = $state([]);
	let loading = $state(false);
	let loaded = $state(false);
	let error = $state('');
	let draftPrompt = $state('');
	let isCreating = $state(false);
	let editingId = $state(0);
	let editTitle = $state('');
	let editDescription = $state('');
	let editCoverUrl = $state('');
	/** @type {Record<number, string>} */
	let busyActions = $state({});
	let displayedMixes = $derived(activeTab === 'owned' ? owned : saved);
	let controller = new AbortController();

	$effect(() => {
		if ($authStore.status === 'guest') {
			void goto(resolve('/login'));
		} else if ($authStore.status === 'authenticated' && !loaded) {
			loaded = true;
			void loadLibrary();
		}
	});

	onDestroy(() => controller.abort());

	async function loadLibrary() {
		loading = true;
		error = '';
		try {
			const library = await getLibrary({ signal: controller.signal });
			owned = library.owned;
			saved = library.saved;
		} catch (requestError) {
			if (!controller.signal.aborted) {
				error =
					requestError instanceof Error ? requestError.message : 'Could not load your library.';
			}
		} finally {
			if (!controller.signal.aborted) {
				loading = false;
			}
		}
	}

	/** @param {SubmitEvent} event */
	async function handleCreate(event) {
		event.preventDefault();
		const prompt = draftPrompt.trim();
		if (!prompt || isCreating) return;
		isCreating = true;
		error = '';
		try {
			const mix = await createMix(prompt);
			owned = [mix, ...owned];
			draftPrompt = '';
			activeTab = 'owned';
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not create the mix.';
		} finally {
			isCreating = false;
		}
	}

	/** @param {Mix} mix */
	function beginEdit(mix) {
		editingId = mix.id;
		editTitle = mix.title;
		editDescription = mix.description || '';
		editCoverUrl = mix.coverUrl;
	}

	function cancelEdit() {
		editingId = 0;
	}

	/** @param {Mix} mix */
	async function handleUpdate(mix) {
		const title = editTitle.trim();
		if (!title || busyActions[mix.id]) return;
		busyActions = { ...busyActions, [mix.id]: 'edit' };
		error = '';
		try {
			const updated = await updateMix(mix.id, {
				title,
				description: editDescription.trim() || null,
				coverUrl: editCoverUrl.trim() || null
			});
			owned = owned.map((item) => (item.id === mix.id ? updated : item));
			cancelEdit();
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not update the mix.';
		} finally {
			clearBusy(mix.id);
		}
	}

	/** @param {Mix} mix */
	async function handlePublish(mix) {
		if (busyActions[mix.id]) return;
		busyActions = { ...busyActions, [mix.id]: 'publish' };
		error = '';
		try {
			const published = await publishMix(mix.id);
			owned = owned.map((item) => (item.id === mix.id ? published : item));
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not publish the mix.';
		} finally {
			clearBusy(mix.id);
		}
	}

	/** @param {Mix} mix */
	async function handleRemoveSaved(mix) {
		if (busyActions[mix.id]) return;
		busyActions = { ...busyActions, [mix.id]: 'remove' };
		error = '';
		try {
			await unsaveMix(mix.id);
			saved = saved.filter((item) => item.id !== mix.id);
		} catch (requestError) {
			error = requestError instanceof Error ? requestError.message : 'Could not remove the mix.';
		} finally {
			clearBusy(mix.id);
		}
	}

	/** @param {number} mixId */
	function clearBusy(mixId) {
		const remaining = { ...busyActions };
		delete remaining[mixId];
		busyActions = remaining;
	}

	/** @param {Mix} mix */
	function playMix(mix) {
		if (!mix.segments.some((segment) => segment.audioUrl)) {
			error = 'This mix has no playable audio.';
			return;
		}
		playerStore.play(mix);
	}
</script>

<svelte:head><title>Your mix library | Zonix</title></svelte:head>

<main class="library-page">
	<header>
		<p class="eyebrow">Your collection</p>
		<h1>Mix library</h1>
		<p>Create persistent drafts, publish them, and revisit saved community mixes.</p>
	</header>

	<form class="create-card card" onsubmit={handleCreate}>
		<label for="mix-prompt">Generate a persistent mix</label>
		<div>
			<input
				id="mix-prompt"
				bind:value={draftPrompt}
				placeholder="Describe the mix you want to keep"
				maxlength="300"
				required
				autocomplete="off"
			/>
			<button class="primary-button" type="submit" disabled={isCreating || !draftPrompt.trim()}>
				{isCreating ? 'Generating…' : 'Generate draft'}
			</button>
		</div>
	</form>

	<div class="tabs" role="tablist" aria-label="Library sections">
		<button
			type="button"
			role="tab"
			aria-selected={activeTab === 'owned'}
			class:active={activeTab === 'owned'}
			onclick={() => (activeTab = 'owned')}>My mixes</button
		>
		<button
			type="button"
			role="tab"
			aria-selected={activeTab === 'saved'}
			class:active={activeTab === 'saved'}
			onclick={() => (activeTab = 'saved')}>Saved mixes</button
		>
	</div>

	{#if error}
		<div class="message error" role="alert">
			<span>{error}</span>
			<button type="button" onclick={() => void loadLibrary()}>Retry</button>
		</div>
	{/if}

	{#if $authStore.status === 'checking' || loading}
		<p class="message" role="status">Loading your library…</p>
	{:else if displayedMixes.length === 0}
		<p class="message">
			{activeTab === 'owned' ? 'No generated drafts yet.' : 'No saved mixes yet.'}
		</p>
	{:else}
		<div class="mix-grid" role="tabpanel">
			{#each displayedMixes as mix (mix.id)}
				<article class="library-card">
					{#if mix.coverUrl}
						<img src={mix.coverUrl} alt="" loading="lazy" />
					{:else}
						<div class="cover-placeholder" aria-hidden="true">ZX</div>
					{/if}

					<div class="content">
						{#if editingId === mix.id}
							<form
								onsubmit={(event) => {
									event.preventDefault();
									void handleUpdate(mix);
								}}
							>
								<label for={`title-${mix.id}`}>Title</label>
								<input id={`title-${mix.id}`} bind:value={editTitle} maxlength="120" required />
								<label for={`description-${mix.id}`}>Description</label>
								<textarea id={`description-${mix.id}`} bind:value={editDescription} maxlength="1000"
								></textarea>
								<label for={`cover-${mix.id}`}>Cover URL</label>
								<input
									id={`cover-${mix.id}`}
									bind:value={editCoverUrl}
									type="url"
									autocomplete="url"
								/>
								<div class="actions">
									<button type="submit" disabled={busyActions[mix.id] === 'edit'}
										>Save changes</button
									>
									<button class="secondary" type="button" onclick={cancelEdit}>Cancel</button>
								</div>
							</form>
						{:else}
							<div class="heading">
								<h2>{mix.title}</h2>
								{#if activeTab === 'owned'}
									<span class:published={mix.status === 'published'}>{mix.status}</span>
								{/if}
							</div>
							<p>{mix.prompt}</p>
							{#if mix.description}<p class="description">{mix.description}</p>{/if}
							<div class="actions">
								<button type="button" onclick={() => playMix(mix)}>Play</button>
								{#if activeTab === 'owned'}
									<button class="secondary" type="button" onclick={() => beginEdit(mix)}
										>Edit</button
									>
									{#if mix.status === 'draft'}
										<button
											type="button"
											disabled={busyActions[mix.id] === 'publish'}
											onclick={() => handlePublish(mix)}
										>
											{busyActions[mix.id] === 'publish' ? 'Publishing…' : 'Publish'}
										</button>
									{/if}
								{:else}
									<button
										class="secondary"
										type="button"
										disabled={busyActions[mix.id] === 'remove'}
										onclick={() => handleRemoveSaved(mix)}
									>
										{busyActions[mix.id] === 'remove' ? 'Removing…' : 'Remove saved'}
									</button>
								{/if}
							</div>
						{/if}
					</div>
				</article>
			{/each}
		</div>
	{/if}
</main>

<style>
	.library-page {
		max-width: 1200px;
		margin: 0 auto;
		padding: 48px 0 180px;
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
	.library-card p,
	.message {
		color: var(--text-soft);
	}
	.create-card {
		display: grid;
		gap: 12px;
		margin: 28px 0;
		padding: 20px;
	}
	.create-card > * {
		position: relative;
		z-index: 1;
	}
	.create-card > div {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 12px;
	}
	.create-card label {
		font-weight: 900;
	}
	.tabs,
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.tabs {
		margin: 24px 0;
	}
	.tabs button,
	button.secondary {
		border: 1px solid var(--border-soft);
		background: transparent;
		color: var(--text-soft);
	}
	.tabs button.active {
		border-color: var(--accent-2);
		background: rgba(59, 130, 246, 0.18);
		color: white;
	}
	button {
		min-height: 42px;
		border: 0;
		border-radius: 999px;
		padding: 9px 14px;
		background: var(--accent);
		color: white;
		font-weight: 800;
	}
	button:disabled {
		cursor: not-allowed;
		opacity: 0.5;
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
		min-height: 90px;
		resize: vertical;
	}
	.mix-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 20px;
	}
	.library-card {
		overflow: hidden;
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-md);
		background: rgba(7, 16, 31, 0.92);
	}
	.library-card > img,
	.cover-placeholder {
		display: grid;
		width: 100%;
		aspect-ratio: 16 / 9;
		place-items: center;
		object-fit: cover;
		background: #0c1c34;
		color: var(--accent-2);
		font-size: 3rem;
		font-weight: 900;
	}
	.content {
		padding: 18px;
	}
	.content form {
		display: grid;
		gap: 8px;
	}
	.heading {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}
	h2 {
		margin: 0;
		font-size: 20px;
	}
	.heading span {
		border-radius: 999px;
		padding: 4px 8px;
		background: rgba(255, 255, 255, 0.08);
		color: var(--text-soft);
		font-size: 12px;
		text-transform: capitalize;
	}
	.heading span.published {
		background: rgba(112, 225, 199, 0.14);
		color: var(--success);
	}
	.description {
		color: var(--text-muted) !important;
	}
	.message {
		padding: 20px;
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-md);
	}
	.message.error {
		display: flex;
		justify-content: space-between;
		border-color: rgba(255, 107, 134, 0.45);
		color: #ffb1bf;
	}
	.message.error button {
		background: transparent;
		color: inherit;
	}
	@media (max-width: 700px) {
		.create-card > div {
			grid-template-columns: 1fr;
		}
	}
</style>
