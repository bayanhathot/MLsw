<script>
  import "../app.css";
  import Navbar from "$lib/components/Navbar.svelte";

  let { children } = $props();
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