<script>
	/** @type {{ attachment: Record<string, any> }} */
	let { attachment } = $props();

	let kind = $derived(String(attachment.kind || ''));
	let url = $derived(String(attachment.url || ''));
	let filename = $derived(String(attachment.filename || 'Attachment'));
</script>

<figure>
	{#if kind === 'image'}
		<img src={url} alt={filename} loading="lazy" />
	{:else if kind === 'video'}
		<!-- User-uploaded media does not currently include a captions sidecar. -->
		<!-- svelte-ignore a11y_media_has_caption -->
		<video src={url} controls preload="metadata"></video>
	{:else if kind === 'audio'}
		<audio src={url} controls preload="metadata"></audio>
	{:else}
		<!-- Backend attachment URLs are API resources, not SvelteKit routes. -->
		<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
		<a href={url} target="_blank" rel="noreferrer">{filename}</a>
	{/if}
	<figcaption>{filename}</figcaption>
</figure>

<style>
	figure {
		display: grid;
		gap: 5px;
		margin: 8px 0 0;
	}
	img,
	video {
		display: block;
		max-width: min(100%, 560px);
		max-height: 360px;
		border-radius: 12px;
		object-fit: contain;
		background: #02050b;
	}
	audio {
		width: min(100%, 560px);
	}
	a {
		color: var(--accent-2);
	}
	figcaption {
		color: var(--text-muted);
		font-size: 12px;
	}
</style>
