<script lang="ts">
  import type { CourseResults } from "$lib/view-models";
  import type { Status } from "$lib/types";
  import { departmentLabel } from "$lib/departments";
  import { Search, X } from "@lucide/svelte";
  import { goto } from "$app/navigation";
  import { activeCourseFilters } from "$lib/course-filter-ui";
  import { activityLabels } from "$lib/course-learning";
  import { courseLearningRelease } from "$lib/course-learning-release";
  import SearchInput from "./SearchInput.svelte";
  import Select from "./Select.svelte";
  import FacetSelect from "./FacetSelect.svelte";
  import CourseList from "./CourseList.svelte";
  import CourseFilters from "./CourseFilters.svelte";
  import { termName } from "$lib/format";
  import { createFacetDistributions } from "$lib/facet-distributions.svelte";

  let {
    results,
    status,
    subject = "",
    path = "/search",
    showTerm = true,
    ranked = false,
    showHeading = true,
  }: {
    results: CourseResults;
    status: Status;
    subject?: string;
    path?: string;
    showTerm?: boolean;
    ranked?: boolean;
    showHeading?: boolean;
  } = $props();
  let draft = $state<URLSearchParams | null>(null);
  let navigationError = $state("");
  let filters = $derived(
    Object.fromEntries(
      Object.entries(
        draft ? Object.fromEntries(draft) : results.filters || {},
      ).filter(
        ([key]) => key !== "activity" || courseLearningRelease.activitySearch,
      ),
    ),
  );
  let active = $derived(
    activeCourseFilters(
      filters,
      status.designations ?? [],
      results.instructor_name,
    ).filter((filter) => !subject || filter.id !== "subject"),
  );
  let searchFilters = $derived({
    ...filters,
    subject: subject || filters.subject || "",
    term: filters.term || results.term,
    availability: filters.availability || results.availability,
  });

  const facets = createFacetDistributions(
    () => ({ ...searchFilters, q: filters.q ?? results.q }),
    () => status.revision,
  );

  function change(updates: Record<string, string>) {
    const query = new URLSearchParams(draft ?? location.search);
    for (const [key, value] of Object.entries(updates)) {
      if (value) query.set(key, value);
      else query.delete(key);
    }
    query.delete("page");
    draft = query;
    navigationError = "";
    const href = `${path}?${query}`;
    void goto(href, { keepFocus: true, noScroll: true })
      .catch(() => {
        if (draft === query)
          navigationError = "Couldn’t update the results. Please try again.";
      })
      .finally(() => {
        if (draft === query) draft = null;
      });
  }
  function clear(keys: string[]) {
    change(Object.fromEntries(keys.map((key) => [key, ""])));
  }
  function pageLink(page: number) {
    return `${path}?${new URLSearchParams({ ...searchFilters, page: String(page) })}`;
  }
</script>

<section aria-label="Find courses" class="finder">
  {#if showHeading}<h2 class="finder-heading">
      {ranked ? "Find your fit" : "Find your next class"}
    </h2>{/if}
  <form action={path} class="finder-search">
    <SearchInput
      value={results.q}
      revision={status.revision}
      filters={searchFilters}
      placeholder="A course, professor, or something you want to learn…"
    />
    {#each Object.entries(searchFilters).filter(([key]) => !["q", "page"].includes(key)) as [key, value] (key)}
      <input type="hidden" name={key} {value} />
    {/each}
    <button class="search-button" aria-label="Search"
      ><Search size={19} strokeWidth={1.5} /></button
    >
  </form>
  <CourseFilters
    {filters}
    {status}
    instructorName={results.instructor_name}
    onChange={change}
    distributions={facets.data}
    pending={facets.pending}
    error={facets.error}
    onRequest={facets.requestGroup}
  >
    {#snippet context()}
      {#if courseLearningRelease.activitySearch}
        <Select
          label="Learning activity"
          value={filters.activity || ""}
          options={[
            { value: "", label: "All learning activities" },
            ...Object.entries(activityLabels).map(([value, label]) => ({
              value,
              label,
            })),
          ]}
          onChange={(value) => change({ activity: value })}
        />
      {/if}
      {#if !subject}
        <FacetSelect
          label="Department"
          distribution={facets.data.subject}
          pending={facets.pending}
          error={facets.error}
          onOpenChange={(open) => facets.requestContext("subject", open)}
          value={filters.subject || ""}
          options={[
            { value: "", label: "All departments" },
            ...status.departments.map((department) => ({
              value: department.subject,
              label: departmentLabel(department.subject),
            })),
            ...(filters.subject?.includes(",")
              ? [
                  {
                    value: filters.subject,
                    label: filters.subject
                      .split(",")
                      .map(departmentLabel)
                      .join(" or "),
                  },
                ]
              : []),
          ]}
          onChange={(value) => change({ subject: value })}
        />
      {/if}
      {#if showTerm}
        <FacetSelect
          label="Term"
          distribution={facets.data.term}
          pending={facets.pending}
          error={facets.error}
          onOpenChange={(open) => facets.requestContext("term", open)}
          value={searchFilters.term}
          options={status.terms.map((term) => ({
            value: term,
            label: termName(term),
          }))}
          onChange={(value) => change({ term: value })}
        />
      {/if}
      <FacetSelect
        label="Course availability"
        distribution={facets.data.availability}
        pending={facets.pending}
        error={facets.error}
        onOpenChange={(open) => facets.requestContext("availability", open)}
        value={searchFilters.availability}
        options={[
          { value: "offered", label: "Recorded offerings" },
          { value: "all", label: "Full catalog" },
        ]}
        onChange={(value) => change({ availability: value })}
      />
    {/snippet}
    {#snippet sorting()}
      {#if !ranked}
        <div class="finder-sort">
          <Select
            label="Sort courses"
            variant="compact"
            value={filters.sort || ""}
            options={[
              { value: "", label: "Course match" },
              { value: "gpa", label: "Higher historical grades" },
            ]}
            onChange={(value) => change({ sort: value })}
          />
        </div>
      {/if}
    {/snippet}
  </CourseFilters>
  {#if active.length}
    <div class="active-filters" aria-label="Active course filters">
      {#each active as filter (filter.id)}
        <button
          type="button"
          class="filter-chip"
          aria-label={`Remove ${filter.label}`}
          onclick={() => clear(filter.keys)}
          ><span>{filter.label}</span><X size={13} aria-hidden="true" /></button
        >
      {/each}
      <button
        type="button"
        class="clear-filters"
        onclick={() => clear(active.flatMap((filter) => filter.keys))}
        >Clear filters</button
      >
    </div>
  {/if}
  <div class="results-heading">
    <p role="status" aria-live="polite">
      {#if draft}Updating results…{:else}<strong
          >{results.total.toLocaleString()}</strong
        >
        {results.total === 1 ? "course" : "courses"}{/if}
    </p>
  </div>
  {#if navigationError}<p role="alert" class="navigation-error">
      {navigationError}
    </p>{/if}
  {#if ranked || filters.sort === "gpa"}<p class="ranking-note">
      {ranked
        ? "Ranked courses have at least 100 recorded letter grades."
        : "Grade sorting prioritizes courses with at least 100 recorded letter grades."}
    </p>{/if}
  <div aria-busy={draft !== null}>
    <CourseList
      courses={results.items}
      rankStart={ranked ? (results.page - 1) * 30 + 1 : undefined}
    />
  </div>
  <nav class="pagination" aria-label="Course results pages">
    {#if results.page > 1}<a href={pageLink(results.page - 1)}>← Previous</a
      >{/if}
    <span>Page {results.page}</span>
    {#if results.page * 30 < results.total}<a href={pageLink(results.page + 1)}
        >Next →</a
      >{/if}
  </nav>
</section>

<style>
  .finder {
    min-width: 0;
  }
  .finder-heading {
    font-size: 27px;
    font-weight: 500;
    margin-bottom: 18px;
  }
  .finder-search {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }
  .finder-search :global(.search-input) {
    flex: 1;
    min-width: 0;
    padding: 0;
    border: 0;
    border-bottom: 1px solid var(--border);
    background: transparent;
    color: var(--text);
    font: inherit;
  }
  .search-button {
    display: grid;
    place-items: center;
    min-height: 42px;
    padding: 8px 10px;
    border: 0;
    background: transparent;
  }
  .active-filters {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin-top: 14px;
  }
  .filter-chip {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    min-height: 34px;
    max-width: 100%;
    text-align: left;
    border-color: transparent;
    background: var(--accent-soft);
    color: var(--accent);
    padding: 6px 10px;
    font-size: 12px;
  }
  .filter-chip span {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .filter-chip :global(svg) {
    flex-shrink: 0;
  }
  .clear-filters {
    border: 0;
    background: transparent;
    font-size: 12px;
    padding: 8px;
    color: var(--muted);
  }
  .finder-sort {
    margin-left: auto;
  }
  .results-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-top: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
    color: var(--muted);
  }
  .results-heading strong {
    font-weight: 500;
    color: var(--text);
  }
  .ranking-note {
    margin-top: 10px;
    color: var(--muted);
    font-size: 12px;
  }
  .navigation-error {
    margin-top: 12px;
    color: var(--accent);
    font-size: 13px;
  }
  .pagination {
    display: flex;
    gap: 24px;
    margin-top: 24px;
    font-size: 13px;
  }
  @media (max-width: 600px) {
    .finder-sort {
      margin-left: 0;
    }
    .finder-search {
      gap: 4px;
    }
  }
</style>
