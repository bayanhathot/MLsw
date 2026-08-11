<script>
	import MiniMixPlayer from './MiniMixPlayer.svelte';
	import { playerStore } from '$lib/stores/playerStore.js';
</script>

{#if $playerStore.mix}
	{#key $playerStore.mix.id}
		<MiniMixPlayer mix={$playerStore.mix} onClose={() => playerStore.close()} />
	{/key}
{/if}
