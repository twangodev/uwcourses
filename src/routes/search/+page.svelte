<script lang="ts">
  import Badges from "$lib/components/Badges.svelte";
  import { instructorBadges } from "$lib/badges";
  import { page } from "$app/state";
  import { Search } from "@lucide/svelte";
  import CourseCollections from "$lib/components/CourseCollections.svelte";
  import CourseFinder from "$lib/components/CourseFinder.svelte";
  import { termName } from "$lib/format";
  let { data } = $props();
  function pageLink(n: number) {
    const q = new URLSearchParams({ ...data.results.filters, page: String(n) });
    return `${page.url.pathname}?${q}`;
  }
</script>

<div
  class="flex justify-between items-baseline gap-6 mt-2 mb-5 search-heading mx-0"
>
  <h1 class="text-[38px] font-medium">
    {data.results.kind === "course" ? "Explore courses" : "Find a professor"}
  </h1>
  <span class="text-[12px] text-muted">{termName(data.status.term)}</span>
</div>
{#if data.results.kind === "course"}
  <CourseCollections />
  <CourseFinder
    showHeading={false}
    path={page.url.pathname}
    results={data.results}
    status={data.status}
  />
  <p class="mt-8 text-[13px] switch">
    <a href="/instructors/by-rating-count">Looking for a professor? →</a>
  </p>
{:else}
  <form action={page.url.pathname} class="flex gap-4 mb-6 instructor-search">
    <input
      class="min-w-0 p-3 border border-border bg-surface text-foreground"
      type="hidden"
      name="kind"
      value="instructor"
    /><input
      class="min-w-0 p-3 border border-border bg-surface text-foreground"
      name="q"
      aria-label="Search instructors"
      placeholder="A professor’s name…"
      value={data.results.q}
    /><button
      class="grid place-items-center border-0 bg-transparent search-submit py-2 px-2.5"
      aria-label="Search"><Search size={19} strokeWidth={1.5} /></button
    >
  </form>
  <p class="muted">{data.results.total} instructors</p>
  {#each data.results.items as i}<article
      class="border-b border-b-border instructor-result py-5 px-0"
    >
      <a
        class="p-0 border-0 flex justify-between flex-wrap gap-y-2 gap-x-6 course-row instructor-result-link"
        href={i.instructor_url}
        ><span>{i.name || "Name unavailable"}</span><span class="muted"
          >{#if i.bayesian_quality != null}{i.bayesian_quality.toFixed(1)}/5
            adjusted ·
          {/if}{i.current
            ? `Teaching in ${termName(data.status.term)}`
            : "Historical instructor"}</span
        ></a
      >
      <Badges badges={instructorBadges(i)} />
    </article>{:else}<p class="empty">
      No instructors match this search.
    </p>{/each}
  <nav class="flex gap-6 mt-6" aria-label="Results pages">
    {#if data.results.page > 1}<a href={pageLink(data.results.page - 1)}
        >← Previous</a
      >{/if}{#if data.results.page * 30 < data.results.total}<a
        href={pageLink(data.results.page + 1)}>Next →</a
      >{/if}
  </nav>
  <p class="mt-8 text-[13px] switch"><a href="/search">Find courses →</a></p>
{/if}

<style>
  .instructor-search input {
    flex: 1;
    font: inherit;
  }
  @media (max-width: 600px) {
    .search-heading {
      flex-direction: column;
      gap: 8px;
    }
  }
</style>
