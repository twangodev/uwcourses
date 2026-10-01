<script lang="ts">
  import type { Snippet } from "svelte";
  import { X, ChevronDown } from "@lucide/svelte";
  import {
    catalogSeasons,
    graduateLevels,
    instructionModes,
    levelBands,
    timeBuckets,
    undergraduateLevels,
    weekdays,
  } from "$lib/course-facets";
  import {
    activeCourseFilters,
    dayLabels,
    filterGroups,
    modeLabels,
    seasonLabels,
    timeLabels,
    tokens,
  } from "$lib/course-filter-ui";
  import { courseTags, courseTagValues } from "$lib/course-tags";
  import type { Status } from "$lib/types";
  import type { DistributionId, FacetResponse } from "$lib/facet-distributions";
  import FacetChart from "./FacetChart.svelte";
  import FilterChoices from "./FilterChoices.svelte";
  import FilterRange from "./FilterRange.svelte";
  import Select from "./Select.svelte";
  import FacetLegend from "./FacetLegend.svelte";
  import InstructorFilter from "./InstructorFilter.svelte";

  let {
    filters,
    status,
    instructorName,
    onChange,
    context,
    sorting,
    distributions,
    pending,
    error,
    onRequest,
  }: {
    filters: Record<string, string>;
    status: Status;
    instructorName?: string | null;
    onChange: (updates: Record<string, string>) => void;
    context: Snippet;
    sorting: Snippet;
    distributions: FacetResponse["distributions"];
    pending: boolean;
    error: string;
    onRequest: (ids: readonly DistributionId[]) => void;
  } = $props();
  const id = $props.id();
  let open = $state<string | null>(null);
  let allInstructors = $state(false);
  const instructorBins = $derived(
    (distributions.instructor?.bins ?? []).filter(
      (bin, index) =>
        allInstructors || index < 6 || bin.value === filters.instructor,
    ),
  );
  let active = $derived(
    activeCourseFilters(filters, status.designations ?? [], instructorName),
  );
  let designationFamilies = $derived([
    ...new Set((status.designations ?? []).map((row) => row.family)),
  ]);
  function change(key: string, value: string) {
    onChange({ [key]: value });
  }
  function count(facets: readonly string[]) {
    return active
      .filter((filter) => facets.includes(filter.id))
      .reduce(
        (total, filter) =>
          total + (filter.id === "tags" ? tokens(filters.tags).length : 1),
        0,
      );
  }
  function close() {
    const trigger = document.getElementById(`${id}-${open}`);
    open = null;
    onRequest([]);
    trigger?.focus();
  }
</script>

<svelte:window
  onkeydown={(event) => {
    if (event.key !== "Escape" || !open || event.defaultPrevented) return;
    if (
      event.target instanceof HTMLInputElement &&
      event.target.getAttribute("role") === "combobox"
    )
      return;
    close();
  }}
/>

<div class="filter-groups" role="group" aria-label="Course filters">
  {@render context()}
  {#each filterGroups as group (group.id)}
    <button
      class="group-trigger"
      class:active={count(group.facets) > 0}
      type="button"
      id={`${id}-${group.id}`}
      aria-label={group.label}
      aria-describedby={count(group.facets)
        ? `${id}-${group.id}-count`
        : undefined}
      aria-expanded={open === group.id}
      aria-controls={`${id}-panel`}
      onclick={() => {
        open = open === group.id ? null : group.id;
        onRequest(open ? group.facets : []);
      }}
    >
      {group.label}
      {#if count(group.facets)}<span
          class="count"
          id={`${id}-${group.id}-count`}
          >{count(group.facets)}<span class="sr-only">
            active filters</span
          ></span
        >{/if}
      <ChevronDown size={14} aria-hidden="true" />
    </button>
  {/each}
  {@render sorting()}
</div>

{#if open}
  <section
    class="filter-panel"
    id={`${id}-panel`}
    aria-labelledby={`${id}-${open}`}
  >
    <div class="panel-heading">
      <span>{filterGroups.find((group) => group.id === open)?.label}</span>
      <button
        class="close"
        type="button"
        aria-label="Close filters"
        onclick={close}><X size={17} /></button
      >
    </div>
    <FacetLegend {pending} />
    {#if error}<p role="alert" class="help">{error}</p>{/if}
    <div
      class="panel-content"
      class:course={open === "course"}
      class:schedule={open === "schedule"}
      aria-busy={pending}
      class:updating={pending}
    >
      {#if open === "tags"}
        <div class="column">
          <FilterChoices
            label="Course highlights"
            value={filters.tags}
            options={courseTagValues.map((value) => ({
              value,
              label: courseTags[value].label,
            }))}
            distribution={distributions.tags}
            onChange={(value) => change("tags", value)}
          />
          <p class="help">Match all selected tags. Click again to remove.</p>
        </div>
        <div class="column tag-definitions">
          {#each courseTagValues as tag (tag)}
            <p>
              <strong>{courseTags[tag].label}</strong>
              {courseTags[tag].description}
            </p>
          {/each}
          <p class="help">
            Grades compare with {tokens(filters.subject).length === 1
              ? "the selected department"
              : "UW–Madison"}. Higher grades are a clue, not a measure of
            workload. Open a result’s badge for its evidence.
          </p>
        </div>
      {:else if open === "course"}
        <div class="column">
          <FilterChoices
            label="Course numbers"
            columns={2}
            distribution={distributions.level}
            value={filters.level}
            options={levelBands.map((band) => ({
              value: String(band),
              label: `${band}–${band + 99}`,
            }))}
            onChange={(value) => change("level", value)}
          >
            {#snippet presets()}
              <div class="shortcuts">
                <button
                  type="button"
                  aria-pressed={tokens(filters.level)
                    .map(Number)
                    .sort((a, b) => a - b)
                    .join(",") === undergraduateLevels.join(",")}
                  onclick={() => change("level", undergraduateLevels.join(","))}
                  >Undergraduate</button
                >
                <button
                  type="button"
                  aria-pressed={tokens(filters.level)
                    .map(Number)
                    .sort((a, b) => a - b)
                    .join(",") === graduateLevels.join(",")}
                  onclick={() => change("level", graduateLevels.join(","))}
                  >Graduate</button
                >
                <button type="button" onclick={() => change("level", "")}
                  >Any level</button
                >
              </div>
            {/snippet}
          </FilterChoices>
        </div>
        <div class="column">
          <FilterRange
            label="Credits"
            distribution={distributions.credits}
            min={filters.credits_min}
            max={filters.credits_max}
            limit={20}
            step={0.5}
            onChange={(bound, value) => change(`credits_${bound}`, value)}
            onRangeChange={(range) =>
              onChange({ credits_min: range.min, credits_max: range.max })}
          />
          <p class="help">
            Variable-credit courses appear at each possible credit value.
          </p>
        </div>
        <div class="column">
          <FilterChoices
            label="Requisites"
            distribution={distributions.requisites}
            value={filters.requisites}
            multiple={false}
            options={[
              { value: "none", label: "No requisites listed" },
              { value: "listed", label: "Requisites listed" },
              {
                value: "unknown",
                label: "Unparsed requisites",
                disabled: true,
              },
            ]}
            onChange={(value) => change("requisites", value)}
          />

          <FilterChoices
            label="Usually offered"
            distribution={distributions.season}
            value={filters.season}
            options={catalogSeasons.map((value) => ({
              value,
              label: seasonLabels[value],
            }))}
            onChange={(value) => change("season", value)}
          />
          <p class="help">
            Seasons come from the catalog. The term above controls recorded
            offerings.
          </p>
          {#if designationFamilies.length}
            {#each designationFamilies as family (family)}
              <FilterChoices
                label={family
                  .split("-")
                  .map((word) => word[0].toUpperCase() + word.slice(1))
                  .join(" ")}
                distribution={distributions.designation}
                value={filters.designation}
                options={(status.designations ?? [])
                  .filter((row) => row.family === family)
                  .map((row) => ({
                    value: `${row.family}:${row.value}`,
                    label: row.label,
                  }))}
                onChange={(value) => change("designation", value)}
              />
            {/each}
            <p class="help">
              Guide designations describe this catalog snapshot; check your
              degree audit for requirement fulfillment.
            </p>
          {/if}
        </div>
      {:else if open === "schedule"}
        <div class="column">
          <FilterChoices
            label="Class days"
            distribution={distributions.days}
            value={filters.days}
            options={weekdays.map((value) => ({
              value,
              label: dayLabels[value],
            }))}
            onChange={(value) =>
              onChange({
                days: value,
                days_match: value ? filters.days_match || "within" : "",
              })}
          />
          <Select
            label="Day match"
            value={filters.days_match || "within"}
            options={[
              { value: "within", label: "Only these days" },
              { value: "any", label: "At least one selected day" },
            ]}
            onChange={(value) => change("days_match", value)}
          />
          <p class="help">
            Bars count courses meeting on each day. “Only these days” keeps
            courses whose recorded class meetings all fall on the days you
            choose.
          </p>
        </div>
        <div class="column">
          <FilterChoices
            label="Class starts"
            distribution={distributions.time}
            value={filters.time}
            options={timeBuckets.map((value) => ({
              value,
              label: timeLabels[value],
            }))}
            onChange={(value) => change("time", value)}
          />
          <p class="help">
            Morning before noon · Afternoon noon–5 pm · Evening after 5 pm
          </p>
        </div>
        <div class="column">
          <FilterChoices
            label="Instruction mode"
            distribution={distributions.mode}
            value={filters.mode}
            options={instructionModes.map((value) => ({
              value,
              label: modeLabels[value],
            }))}
            onChange={(value) => change("mode", value)}
          />
        </div>
        <p class="help full-width">
          Uses recorded class meetings in the selected term, Central time. Exams
          are excluded.
        </p>
      {:else if open === "grades"}
        <div class="full-width">
          <FilterRange
            label="Historical GPA"
            distribution={distributions.gpa}
            min={filters.gpa_min}
            max={filters.gpa_max}
            maxExclusive={filters.gpa_max_exclusive === "true"}
            limit={4}
            step={0.1}
            onChange={(bound, value) =>
              onChange({
                [`gpa_${bound}`]: value,
                ...(bound === "max" ? { gpa_max_exclusive: "" } : {}),
              })}
            onRangeChange={(range) =>
              onChange({
                gpa_min: range.min,
                gpa_max: range.max,
                gpa_max_exclusive: range.maxExclusive ? "true" : "",
              })}
            inline
          >
            <div class="shortcuts" aria-label="GPA shortcuts">
              {#each ["3", "3.5"] as value}<button
                  type="button"
                  onclick={() => change("gpa_min", value)}
                  >At least {value}</button
                >{/each}
            </div>
            <p class="help">
              Average letter grades over up to five years through the selected
              term. Courses without recorded letter grades in that window are
              excluded when a GPA filter is set.
            </p>
          </FilterRange>
        </div>
      {:else if open === "instructor"}
        <div class="column">
          <p class="help">Most common instructors in these results</p>
          {#if distributions.instructor}
            <FacetChart
              label="Instructor"
              bins={instructorBins}
              selected={filters.instructor ? [filters.instructor] : []}
              onPick={(uid) =>
                change("instructor", filters.instructor === uid ? "" : uid)}
            />{:else}<div
              class="instructor-placeholder"
              class:loading={pending}
              aria-label={pending
                ? "Loading instructor distribution"
                : "Instructor distribution unavailable"}
            >
              {#each Array(6) as _}
                <div class="instructor-skeleton">
                  <span></span><span></span>
                </div>
              {/each}
            </div>{/if}
          {#if (distributions.instructor?.bins.length ?? 0) > 6}<button
              class="more-instructors"
              type="button"
              onclick={() => (allInstructors = !allInstructors)}
              >{allInstructors
                ? "Show fewer instructors"
                : "Show more instructors"}</button
            >{/if}
        </div>
        <div class="column">
          <InstructorFilter
            revision={status.revision}
            name={instructorName}
            onPick={(uid) => change("instructor", uid)}
          />
          <p class="help">
            For recorded offerings, the instructor must teach the course in the
            selected term. Full catalog includes their recorded teaching in any
            term.
          </p>
        </div>
      {/if}
    </div>
  </section>
{/if}

<style>
  .filter-groups {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .filter-groups :global(.course-select-trigger) {
    min-height: 38px;
    max-width: min(100%, 260px);
    background: transparent;
  }
  .group-trigger {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 38px;
    background: transparent;
    padding: 7px 12px;
    font-size: 12px;
  }
  .group-trigger.active {
    border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
    color: var(--accent);
  }
  .group-trigger[aria-expanded="true"] {
    background: var(--surface);
    border-color: var(--text);
    color: var(--text);
  }
  .group-trigger[aria-expanded="true"] :global(svg) {
    transform: rotate(180deg);
  }
  .count {
    font-size: 11px;
    line-height: 18px;
    min-width: 18px;
    border-radius: 50%;
    text-align: center;
    background: var(--accent-soft);
    color: var(--accent);
  }
  .filter-panel {
    border: 1px solid var(--border);
    border-radius: var(--radius-surface);
    margin-top: 12px;
    padding: 12px 18px 18px;
    background: var(--surface);
  }
  .panel-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
    font-size: 14px;
    font-weight: 500;
  }
  .close {
    border: 0;
    background: transparent;
    display: grid;
    place-items: center;
    padding: 8px;
  }
  .updating {
    --chart-opacity: 0.8;
  }
  .panel-content {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 20px 24px;
    margin-top: 14px;
  }
  .panel-content.course,
  .panel-content.schedule {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .column {
    display: grid;
    align-content: start;
    justify-items: start;
    gap: 14px;
    min-width: 0;
  }
  .tag-definitions {
    gap: 10px;
    font-size: 12px;
    line-height: 1.5;
    color: var(--muted);
  }
  .tag-definitions p {
    margin: 0;
  }
  .tag-definitions strong {
    color: var(--text);
    font-weight: 500;
  }
  .shortcuts {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .shortcuts button {
    min-height: 36px;
    padding: 6px 10px;
    background: var(--bg);
    font-size: 13px;
  }
  .shortcuts button[aria-pressed="true"] {
    border-color: var(--accent);
    color: var(--accent);
    background: var(--accent-soft);
  }
  .instructor-placeholder {
    display: grid;
    width: 100%;
    height: 216px;
    font-size: 11px;
    color: var(--muted);
  }
  .instructor-skeleton {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 8px 10px;
  }
  .instructor-skeleton span {
    height: 8px;
    width: 60%;
    background: var(--border);
    border-radius: var(--radius-control);
  }
  .instructor-skeleton span:last-child {
    width: 38px;
  }
  .more-instructors {
    border: 0;
    padding: 4px 0;
    background: transparent;
    color: var(--muted);
    font-size: 12px;
  }
  @media (prefers-reduced-motion: no-preference) {
    .instructor-placeholder.loading {
      animation: instructor-pulse 1.4s ease-in-out infinite alternate;
    }
    @keyframes instructor-pulse {
      to {
        opacity: 0.45;
      }
    }
    .filter-panel {
      animation: filter-arrive var(--motion-normal) var(--motion-ease);
    }
    @keyframes filter-arrive {
      from {
        opacity: 0;
        translate: 0 -3px;
      }
    }
  }
  .help {
    font-size: 12px;
    line-height: 1.6;
    color: var(--muted);
    margin: 0;
    max-width: 72ch;
  }
  .full-width {
    grid-column: 1 / -1;
  }
  @media (max-width: 900px) {
    .panel-content.course,
    .panel-content.schedule {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
  @media (max-width: 600px) {
    .filter-groups {
      gap: 6px;
    }
    .group-trigger,
    .filter-groups :global(.course-select-trigger) {
      min-height: 42px;
    }
    .filter-panel {
      padding: 14px;
    }
    .panel-content,
    .panel-content.course,
    .panel-content.schedule {
      grid-template-columns: minmax(0, 1fr);
      gap: 20px;
    }
  }
</style>
