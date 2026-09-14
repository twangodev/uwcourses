<script lang="ts">
  import { postDate } from "$lib/blog-format";
  let { data } = $props();
</script>

<div class="mx-auto max-w-190 py-8 sm:py-14">
  <header class="mb-12">
    <p class="text-muted mb-3 text-sm">UW Courses</p>
    <h1 class="mb-4 text-4xl font-semibold tracking-tight sm:text-5xl">Blog</h1>
    <p class="text-muted text-lg">
      Updates and notes on exploring UW–Madison courses.
    </p>
  </header>
  <a class="mb-6 inline-block text-sm" href="/blog/rss.xml">Subscribe via RSS</a
  >
  {#each data.posts as post}
    <article class="border-t border-border py-7">
      <time class="text-muted text-sm" datetime={post.date}
        >{postDate(post.date)}</time
      >
      <h2 class="mt-2 mb-3 text-2xl font-semibold tracking-tight">
        <a href={`/blog/${post.slug}`}>{post.title}</a>
      </h2>
      <p class="text-muted">{post.description}</p>
    </article>
  {:else}
    <p class="border-t border-border py-7 text-muted">
      No posts yet. Check back soon.
    </p>
  {/each}
</div>
