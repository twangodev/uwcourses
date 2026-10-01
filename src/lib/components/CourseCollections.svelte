<script lang="ts">
  import { courseCollections } from "$lib/course-collections";
  let {
    subject = "",
    term = "",
    active = "",
  }: { subject?: string; term?: string; active?: string } = $props();
  let query = $derived(
    new URLSearchParams({
      ...(term ? { term } : {}),
    }).toString(),
  );
</script>

<nav
  aria-label="Course collections"
  class="flex flex-wrap gap-y-2 gap-x-6 mt-2 mb-5 collections mx-0"
>
  {#each Object.entries(courseCollections) as [slug, collection]}
    <a
      class="inline-flex items-center gap-3.5 border-b border-b-border text-[13px] py-2 px-0"
      href={`${subject ? `/departments/${encodeURIComponent(subject)}` : "/courses"}/${slug}${query ? `?${query}` : ""}`}
      aria-current={active === slug ? "page" : undefined}
      >{collection.title}<span class="text-muted" aria-hidden="true">↗</span></a
    >
  {/each}
</nav>

<style>
  a[aria-current="page"] {
    color: var(--accent);
    border-color: var(--accent);
  }
</style>
