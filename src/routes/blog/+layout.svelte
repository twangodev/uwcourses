<script lang="ts">
  import "katex/dist/katex.min.css";
  let { children } = $props();
</script>

<svelte:head>
  <link
    rel="alternate"
    type="application/rss+xml"
    title="UW Courses Blog"
    href="/blog/rss.xml"
  />
</svelte:head>

{@render children()}

<style>
  /* KaTeX uses .accent for mathematical accents such as \bar{x}. */
  :global(.blog-prose .katex .accent) {
    color: inherit;
  }
  :global(.blog-prose .katex-display) {
    overflow-x: auto;
    overflow-y: hidden;
    padding-block: 0.25rem;
  }
</style>
