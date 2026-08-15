<script>
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';

	onMount(() => {
		void goto(resolve('/messages'), { replaceState: true });
	});
</script>

<svelte:head><title>Messages | Cuemix</title></svelte:head>

<main class="redirect-page">
	<p>Opening Messages…</p>
	<a href={resolve('/messages')}>Continue</a>
</main>

<style>
	.redirect-page {
		display: grid;
		min-height: 55vh;
		place-content: center;
		justify-items: center;
		gap: 10px;
		color: #8fa2bc;
	}
	.redirect-page a {
		color: #a5cfff;
		font-weight: 900;
	}
</style>
