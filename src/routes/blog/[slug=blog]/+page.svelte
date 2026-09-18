<script lang="ts">
  import { postDate } from "$lib/blog-format";
  let { data } = $props();
</script>

<article class="mx-auto max-w-190 py-8 sm:py-14">
  {#if data.post.draft}<p
      class="mb-6 border border-border bg-surface p-4 text-sm"
    >
      Draft preview · Excluded from the public blog, RSS, and sitemap.
    </p>{/if}
  <a class="text-sm" href="/blog">← All posts</a>
  <header class="mt-8 mb-10 border-b border-border pb-8">
    <time class="text-muted text-sm" datetime={data.post.date}
      >{postDate(data.post.date)}</time
    >
    <h1 class="mt-3 mb-5 text-4xl font-semibold tracking-tight sm:text-5xl">
      {data.post.title}
    </h1>
    <p class="text-muted text-lg">{data.post.description}</p>
  </header>
  <div class="blog-prose"><data.component /></div>
</article>

<style>
  .blog-prose {
    font-size: 1.0625rem;
    line-height: 1.8;
    overflow-wrap: anywhere;
  }
  .blog-prose :global(p),
  .blog-prose :global(ul),
  .blog-prose :global(ol),
  .blog-prose :global(blockquote),
  .blog-prose :global(pre),
  .blog-prose :global(table) {
    margin-block: 1.4em;
  }
  .blog-prose :global(h2),
  .blog-prose :global(h3),
  .blog-prose :global(h4) {
    margin-block: 1.8em 0.6em;
    font-weight: 600;
    line-height: 1.3;
  }
  .blog-prose :global(h2) {
    font-size: 1.65rem;
  }
  .blog-prose :global(h3) {
    font-size: 1.3rem;
  }
  .blog-prose :global(a) {
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .blog-prose :global(ul) {
    list-style: disc;
    padding-left: 1.5em;
  }
  .blog-prose :global(ol) {
    list-style: decimal;
    padding-left: 1.5em;
  }
  .blog-prose :global(li) {
    margin-block: 0.4em;
  }
  .blog-prose :global(blockquote) {
    border-left: 3px solid var(--accent);
    padding-left: 1.25em;
    color: var(--muted);
  }
  .blog-prose :global(pre) {
    overflow-x: auto;
    padding: 1.25rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    font-size: 0.85em;
  }
  .blog-prose :global(code) {
    font-size: 0.9em;
  }
  .blog-prose :global(img) {
    max-width: 100%;
    height: auto;
    border-radius: var(--radius-control);
  }
  .blog-prose :global(table) {
    display: block;
    overflow-x: auto;
    border-collapse: collapse;
  }
  .blog-prose :global(th),
  .blog-prose :global(td) {
    padding: 0.6em 1em;
    border: 1px solid var(--border);
    text-align: left;
  }
  .blog-prose :global(hr) {
    margin-block: 2em;
    border-color: var(--border);
  }
  .blog-prose :global(.footnotes) {
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    font-size: 0.875rem;
    line-height: 1.7;
  }
  .blog-prose :global(.footnotes li),
  .blog-prose :global(sup[id^="blog-fnref-"]) {
    scroll-margin-top: 2rem;
  }
  .blog-prose :global(.footnotes li:target) {
    background: var(--accent-soft);
    outline: 2px solid var(--accent-soft);
  }
  .blog-prose :global(.footnote-ref),
  .blog-prose :global(.footnote-backref) {
    color: var(--accent);
    text-decoration: none;
    padding-inline: 0.2em;
  }
  .blog-prose :global(.footnote-ref:focus-visible),
  .blog-prose :global(.footnote-backref:focus-visible) {
    outline: 2px solid var(--accent);
    outline-offset: 3px;
  }
</style>
