<script lang="ts">
  import {
    catalogSeasons,
    graduateLevels,
    instructionModes,
    levelBands,
    panelFacets,
    timeBuckets,
    undergraduateLevels,
  } from "$lib/course-facets";
  import DayFilter from "./DayFilter.svelte";
  import InstructorFilter from "./InstructorFilter.svelte";
  import Select from "./Select.svelte";

  let {
    filters,
    designations = [],
    revision,
    instructorName = null,
    onChange,
  }: {
    filters: Record<string, string>;
    designations?: { family: string; value: string; label: string }[];
    revision: string;
    instructorName?: string | null;
    onChange: (key: string, value: string) => void;
  } = $props();

  const modeLabels = {
    in_person: "In person",
    online: "Online",
    mixed: "Mixed",
  } as const;
  const timeLabels = {
    morning: "Morning",
    afternoon: "Afternoon",
    evening: "Evening",
  } as const;
  const seasonLabels = { fall: "Fall", spring: "Spring", summer: "Summer" } as const;
  let families = $derived(groupDesignations(designations));

  function selected(name: string) {
    return new Set(
      (filters[name] || "")
        .split(",")
        .map((token) => token.trim())
        .filter(Boolean),
    );
  }

  function toggle(name: string, token: string) {
    const next = selected(name);
    if (next.has(token)) next.delete(token);
    else next.add(token);
    onChange(name, [...next].join(","));
  }

  function groupDesignations(
    rows: { family: string; value: string; label: string }[],
  ) {
    const groups: {
      family: string;
      rows: { family: string; value: string; label: string }[];
    }[] = [];
    for (const row of rows) {
      const group = groups.find((item) => item.family === row.family);
      if (group) group.rows.push(row);
      else groups.push({ family: row.family, rows: [row] });
    }
    return groups;
  }

  </script>

<div class="grid gap-5">
  {#each panelFacets() as facet (facet.id)}
    {#if facet.id === "level"}
      <fieldset class="m-0 border-0 p-0">
        <legend class="mb-2 text-[12px] text-muted">Course number</legend>
        <div class="mb-2 flex flex-wrap gap-2">
          <button type="button" class="shortcut" onclick={() => onChange("level", undergraduateLevels.join(","))}>Undergraduate</button>
          <button type="button" class="shortcut" onclick={() => onChange("level", graduateLevels.join(","))}>Graduate</button>
        </div>
        <div class="flex flex-wrap gap-x-4 gap-y-2">
          {#each levelBands as band (band)}
            <label class="inline-flex items-center gap-2 text-[12px]">
              <input
                type="checkbox"
                checked={selected("level").has(String(band))}
                onchange={() => toggle("level", String(band))}
              />
              {band}–{band + 99}
            </label>
          {/each}
        </div>
      </fieldset>
    {:else if facet.id === "credits"}
      <fieldset class="m-0 flex flex-wrap gap-4 border-0 p-0">
        <legend class="mb-2 w-full text-[12px] text-muted">Credits</legend>
        <label class="grid gap-1 text-[12px] text-muted">
          At least
          <input
            class="number"
            aria-label="At least this many credits"
            type="number"
            min="0"
            max="20"
            step="0.5"
            value={filters.credits_min || ""}
            onchange={(event) => onChange("credits_min", event.currentTarget.value)}
          />
        </label>
        <label class="grid gap-1 text-[12px] text-muted">
          Up to
          <input
            class="number"
            aria-label="Up to this many credits"
            type="number"
            min="0"
            max="20"
            step="0.5"
            value={filters.credits_max || ""}
            onchange={(event) => onChange("credits_max", event.currentTarget.value)}
          />
        </label>
      </fieldset>
    {:else if facet.id === "gpa"}
      <fieldset class="m-0 border-0 p-0">
        <legend class="mb-2 text-[12px] text-muted">Historical GPA</legend>
        <div class="mb-2 flex flex-wrap gap-2">
          {#each ["3", "3.5"] as shortcut (shortcut)}
            <button type="button" class="shortcut" onclick={() => onChange("gpa_min", shortcut)}>At least {shortcut}</button>
          {/each}
        </div>
        <div class="flex flex-wrap gap-4">
          <label class="grid gap-1 text-[12px] text-muted">
            At least
            <input
              class="number"
              aria-label="Historical GPA at least"
              type="number"
              min="0"
              max="4"
              step="0.1"
              value={filters.gpa_min || ""}
              onchange={(event) => onChange("gpa_min", event.currentTarget.value)}
            />
          </label>
          <label class="grid gap-1 text-[12px] text-muted">
            At most
            <input
              class="number"
              aria-label="Historical GPA at most"
              type="number"
              min="0"
              max="4"
              step="0.1"
              value={filters.gpa_max || ""}
              onchange={(event) => onChange("gpa_max", event.currentTarget.value)}
            />
          </label>
        </div>
      </fieldset>
    {:else if facet.id === "requisites"}
      <Select
        label="Requisites"
        value={filters.requisites || ""}
        options={[
          { value: "", label: "Any requisites" },
          { value: "none", label: "No requisites listed" },
          { value: "listed", label: "Requisites listed" },
        ]}
        onChange={(value) => onChange("requisites", value)}
      />
    {:else if facet.id === "season"}
      <fieldset class="m-0 border-0 p-0">
        <legend class="mb-2 text-[12px] text-muted">Catalog season</legend>
        <div class="flex flex-wrap gap-x-4 gap-y-2">
          {#each catalogSeasons as season (season)}
            <label class="inline-flex items-center gap-2 text-[12px]">
              <input
                type="checkbox"
                checked={selected("season").has(season)}
                onchange={() => toggle("season", season)}
              />
              {seasonLabels[season]}
            </label>
          {/each}
        </div>
      </fieldset>
    {:else if facet.id === "designation"}
      <fieldset class="m-0 border-0 p-0">
        <legend class="mb-2 text-[12px] text-muted">Catalog designation</legend>
        {#if families.length}
          <div class="grid gap-3">
            {#each families as group (group.family)}
              <div class="flex flex-wrap gap-x-4 gap-y-2">
                {#each group.rows as row (`${row.family}:${row.value}`)}
                  <label class="inline-flex items-center gap-2 text-[12px]">
                    <input
                      type="checkbox"
                      checked={selected("designation").has(`${row.family}:${row.value}`)}
                      onchange={() => toggle("designation", `${row.family}:${row.value}`)}
                    />
                    {row.label}
                  </label>
                {/each}
              </div>
            {/each}
          </div>
        {:else}
          <p class="m-0 text-[12px] text-muted">Catalog designations are not in this snapshot yet.</p>
        {/if}
      </fieldset>
    {:else if facet.id === "instructor"}
      <InstructorFilter
        {revision}
        name={instructorName}
        onPick={(uid) => onChange("instructor", uid)}
      />
    {:else if facet.id === "days"}
      <DayFilter
        days={filters.days || ""}
        match={filters.days_match === "any" ? "any" : "within"}
        onDays={(days) => onChange("days", days)}
        onMatch={(match) => onChange("days_match", match)}
      />
    {:else if facet.id === "time"}
      <fieldset class="m-0 border-0 p-0">
        <legend class="mb-2 text-[12px] text-muted">Time of day</legend>
        <div class="flex flex-wrap gap-x-4 gap-y-2">
          {#each timeBuckets as bucket (bucket)}
            <label class="inline-flex items-center gap-2 text-[12px]">
              <input
                type="checkbox"
                checked={selected("time").has(bucket)}
                onchange={() => toggle("time", bucket)}
              />
              {timeLabels[bucket]}
            </label>
          {/each}
        </div>
      </fieldset>
    {:else if facet.id === "mode"}
      <fieldset class="m-0 border-0 p-0">
        <legend class="mb-2 text-[12px] text-muted">Meets</legend>
        <div class="flex flex-wrap gap-x-4 gap-y-2">
          {#each instructionModes as mode (mode)}
            <label class="inline-flex items-center gap-2 text-[12px]">
              <input
                type="checkbox"
                checked={selected("mode").has(mode)}
                onchange={() => toggle("mode", mode)}
              />
              {modeLabels[mode]}
            </label>
          {/each}
        </div>
      </fieldset>
    {/if}
  {/each}
</div>

<style>
  .shortcut,
  .number {
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    font: inherit;
  }
  .shortcut {
    min-height: 2rem;
    padding: 0 0.5rem;
    font-size: 12px;
  }
  .number {
    width: 6rem;
    padding: 0.25rem 0.5rem;
    font-size: 12px;
  }
</style>
