<script>
	import { onDestroy } from 'svelte';

	import { uploadAndWait } from '$lib/services/uploadApi.js';

	/** @type {{ disabled?: boolean, onUploaded?: (attachment: Record<string, any>) => void }} */
	let { disabled = false, onUploaded = () => {} } = $props();

	/** @type {File | null} */
	let selectedFile = $state(null);
	/** @type {HTMLInputElement | null} */
	let fileInput = $state(null);
	let uploading = $state(false);
	let status = $state('');
	let error = $state('');
	let controller = new AbortController();

	onDestroy(() => controller.abort());

	/** @param {Event} event */
	function selectFile(event) {
		const input = /** @type {HTMLInputElement} */ (event.currentTarget);
		selectedFile = input.files?.[0] || null;
		status = '';
		error = '';
	}

	async function upload() {
		if (!selectedFile || uploading || disabled) return;
		uploading = true;
		status = 'Queued for processing…';
		error = '';
		try {
			const attachment = await uploadAndWait(selectedFile, { signal: controller.signal });
			onUploaded(attachment);
			status = `${selectedFile.name} is attached.`;
			selectedFile = null;
			if (fileInput) fileInput.value = '';
		} catch (requestError) {
			if (!controller.signal.aborted) {
				error = requestError instanceof Error ? requestError.message : 'Could not upload the file.';
			}
		} finally {
			uploading = false;
		}
	}
</script>

<div class="uploader">
	<label>
		<span>Add image, audio, or video</span>
		<input
			bind:this={fileInput}
			type="file"
			accept="image/jpeg,image/png,image/webp,audio/mpeg,audio/wav,video/mp4,video/webm"
			disabled={disabled || uploading}
			onchange={selectFile}
		/>
	</label>
	<button type="button" disabled={disabled || uploading || !selectedFile} onclick={upload}>
		{uploading ? 'Processing…' : 'Upload attachment'}
	</button>
	{#if status}<small role="status">{status}</small>{/if}
	{#if error}<small class="error" role="alert">{error}</small>{/if}
</div>

<style>
	.uploader {
		display: grid;
		gap: 8px;
		padding: 12px;
		border: 1px dashed var(--border-soft);
		border-radius: 12px;
	}
	label {
		display: grid;
		gap: 7px;
		color: var(--text-soft);
		font-size: 13px;
		font-weight: 800;
	}
	input {
		width: 100%;
		color: var(--text-muted);
	}
	button {
		justify-self: start;
		min-height: 38px;
		border: 1px solid var(--border-soft);
		border-radius: 999px;
		padding: 8px 12px;
		background: rgba(125, 183, 255, 0.08);
		color: var(--text-main);
		font-weight: 800;
	}
	button:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}
	small {
		color: var(--success);
	}
	small.error {
		color: #ffb1bf;
	}
</style>
