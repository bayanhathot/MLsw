<!--
  File: src/lib/components/Skeleton.svelte
  Purpose: A single shimmering placeholder block, sized to stand in for
  whatever real content is about to load. Composed into shapes (see
  PostCardSkeleton.svelte) rather than a full-page spinner.
-->

<script>
  /**
   * @type {{ width?: string, height?: string, radius?: string }}
   */
  let { width = "100%", height = "16px", radius = "8px" } = $props();
</script>

<span
  class="skeleton"
  style={`width: ${width}; height: ${height}; border-radius: ${radius};`}
></span>

<style>
  .skeleton {
    display: block;
    background: linear-gradient(
      90deg,
      var(--bg-panel) 25%,
      rgba(125, 183, 255, 0.16) 37%,
      var(--bg-panel) 63%
    );
    background-size: 400% 100%;
    animation: shimmer-sweep 1.4s ease-in-out infinite;
  }
</style>
