<script lang="ts">
  import type { CourseResults } from "$lib/view-models";
  import type { Status } from "$lib/types";
  import { departmentLabel } from "$lib/departments";
  import { Search } from "@lucide/svelte";
  import { goto } from "$app/navigation";
  import SearchInput from "./SearchInput.svelte";
  import Select from "./Select.svelte";
  import CourseList from "./CourseList.svelte";
  import FacetControls from "./FacetControls.svelte";
  import { panelFacets } from "$lib/course-facets";
  import { termName } from "$lib/format";
  let {
    results,
    status,
    subject = "",
    path = "/search",
    showTerm = true,
    ranked = false,
  }: {
    results: CourseResults;
    status: Status;
    subject?: string;
    path?: string;
    showTerm?: boolean;
    ranked?: boolean;
  } = $props();
  let draft: URLSearchParams | null = null;
  let navigation = Promise.resolve();
  function change(key: string, value: string) {
    const query = new URLSearchParams(draft ?? location.search);
    if (value) query.set(key, value);
    else query.delete(key);
    query.delete("page");
    draft = query;
    const href = `${path}?${query}`;
    navigation = navigation.then(async () => {
      await goto(href, { keepFocus: true, noScroll: true });
      if (draft === query) draft = null;
    });
  }
  let urlParams = $derived(results.filters || {});
  const panelParams = panelFacets().flatMap((facet) =>
    facet.params.map((param) => param.name),
  );
  let advanced = $derived(panelParams.some((name) => urlParams[name]));
  let disclosure = $state<HTMLDetailsElement>();
  let chips = $derived(
    panelFacets().flatMap((facet) =>
      facet.params
        .filter((param) => param.name !== "days_match" && urlParams[param.name])
        .map((param) => ({
          name: param.name,
          label: chipLabel(facet.label, param.name, urlParams[param.name]),
        })),
    ),
  );
  $effect(() => {
    if (advanced && disclosure) disclosure.open = true;
  });
  function chipLabel(facet: string, name: string, value: string) {
    if (name === "instructor")
      return results.instructor_name || "Unknown instructor";
    if (name === "designation") {
      const labels = new Map(
        (status.designations || []).map((row) => [
          `${row.family}:${row.value}`,
          row.label,
        ]),
      );
      return value
        .split(",")
        .map((token) => labels.get(token) || token)
        .join(", ");
    }
    return `${facet}: ${value}`;
  }
  function pageLink(page: number) {
    const query = new URLSearchParams({ ...urlParams, page: String(page) });
    return `${path}?${query}`;
  }
</script>

<section aria-label="Find courses" class="finder">
  <div class="flex items-baseline justify-between gap-5 mb-6 finder-heading">
    <h2 class="text-[27px] font-medium m-0">
      {ranked ? "Find your fit" : "Find your next class"}
    </h2>
    <span class="text-[13px] muted"
      ><strong>{results.total}</strong> courses</span
    >
  </div>
  <form action={path} class="flex items-center gap-3 finder-search">
    <SearchInput
      value={results.q}
      revision={status.revision}
      filters={{
        ...urlParams,
        subject: subject || urlParams.subject || "",
        term: results.term,
        availability: results.availability,
      }}
      placeholder="A course, professor, or something you want to learn…"
    />{#each Object.entries( { ...urlParams, term: results.term, availability: results.availability } ).filter(([key]) => !["q", "page"].includes(key)) as [key, value] (key)}<input
        type="hidden"
        name={key}
        {value}
      />{/each}<button
      class="grid place-items-center min-h-10.5 border-0 bg-transparent shrink-0 py-2 px-2.5"
      aria-label="Search"><Search size={19} strokeWidth={1.5} /></button
    >
  </form>
  <div class="flex flex-wrap gap-2.5 finder-filters my-5.5 mx-0">
    {#if !subject}<Select
        label="Department"
        value={urlParams.subject || ""}
        options={[
          { value: "", label: "All departments" },
          ...status.departments.map((d) => ({
            value: d.subject,
            label: departmentLabel(d.subject),
          })),
        ]}
        onChange={(v) => change("subject", v)}
      />{/if}
    {#if showTerm}
      <Select
        label="Term"
        value={results.term}
        options={status.terms.map((term: string) => ({
          value: term,
          label: termName(term),
        }))}
        onChange={(v) => change("term", v)}
      />
    {/if}
    <Select
      label="Course availability"
      value={results.availability}
      options={[
        { value: "offered", label: "Recorded offerings" },
        { value: "all", label: "Full catalog" },
      ]}
      onChange={(v) => change("availability", v)}
    />
    {#if !ranked}<Select
        label="Sort courses"
        value={urlParams.sort || ""}
        options={[
          { value: "", label: "Course match" },
          { value: "gpa", label: "Higher historical grades" },
        ]}
        onChange={(v) => change("sort", v)}
      />{/if}
  </div>
  {#if chips.length}
    <ul class="m-0 flex list-none flex-wrap gap-2 p-0" aria-label="Active filters">
      {#each chips as chip (chip.name)}
        <li>
          <button
            class="inline-flex max-w-full items-center gap-2 border border-border bg-surface px-2 py-1 text-left text-[12px]"
            type="button"
            onclick={() => change(chip.name, "")}
          >
            <span class="truncate">{chip.label}</span>
            <span aria-hidden="true">×</span>
            <span class="sr-only">Remove {chip.label}</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
  <details class="mt-4" bind:this={disclosure}>
    <summary class="cursor-pointer text-[13px]">Filters</summary>
    <div class="mt-4">
      <FacetControls
        filters={urlParams}
        designations={status.designations || []}
        revision={status.revision}
        instructorName={results.instructor_name}
        onChange={change}
      />
    </div>
  </details>
  <p class="text-[12px] text-muted max-w-[75ch] mt-4 mb-2 coverage mx-0">
    Historical grades cover up to five years through the selected term. Courses
    with no letter grades in that window do not match a GPA floor or ceiling.
    Days and time use class meetings in the selected term, Central time, and
    ignore exams. A catalog designation is the Guide label in this snapshot,
    not a degree-audit decision.
    {ranked
      ? "Only courses with at least 100 letter grades are ranked."
      : "Grade sorting prioritizes courses with at least 100 letter grades."}
  </p>
  <CourseList
    courses={results.items}
    rankStart={ranked ? (results.page - 1) * 30 + 1 : undefined}
  />
  <nav
    class="flex gap-6 mt-6 text-[13px] pagination"
    aria-label="Course results pages"
  >
    {#if results.page > 1}<a href={pageLink(results.page - 1)}>← Previous</a
      >{/if}<span>Page {results.page}</span
    >{#if results.page * 30 < results.total}<a href={pageLink(results.page + 1)}
        >Next →</a
      >{/if}
  </nav>
</section>

<style>
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
</style>
