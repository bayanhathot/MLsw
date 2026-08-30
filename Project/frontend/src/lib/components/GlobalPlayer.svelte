<script>
	import MiniMixPlayer from './MiniMixPlayer.svelte';
	import ProviderManifestPlayer from './ProviderManifestPlayer.svelte';
	import { playerStore } from '$lib/stores/playerStore.js';
</script>

{#if $playerStore.mix}
	{#key $playerStore.mix.id}
		{#if $playerStore.mix.publicationMode === 'provider_manifest'}
			<ProviderManifestPlayer mix={$playerStore.mix} onClose={() => playerStore.close()} />
		{:else}
			<MiniMixPlayer mix={$playerStore.mix} onClose={() => playerStore.close()} />
		{/if}
	{/key}
{/if}
