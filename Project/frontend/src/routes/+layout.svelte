<!--
  File: src/routes/+layout.svelte
  Purpose: Root SvelteKit layout shared by all pages.
  What it does:
  - Imports global CSS once for the whole app.
  - Renders the Navbar above every route.
  - Provides the main centered app shell width.
  - Uses Svelte 5 {@render children()} to display the active route page.
  Why this file exists:
  - In SvelteKit, +layout.svelte replaces the old Vite App.svelte outer shell.
-->

<script>
	import { onMount } from 'svelte';

	import '../app.css';
	import Navbar from '$lib/components/Navbar.svelte';
	import { authStore } from '$lib/stores/authStore.js';

	let { children } = $props();

	onMount(() => {
		authStore.checkAuth();
	});
</script>

<div class="app-shell">
	<Navbar />

	{@render children()}
</div>

<style>
	.app-shell {
		width: min(1500px, calc(100% - 32px));
		margin: 0 auto;
	}
</style>
