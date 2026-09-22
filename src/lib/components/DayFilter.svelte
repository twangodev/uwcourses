<script lang="ts">
  import Select from "./Select.svelte";
  import { weekdays, type DayMatch, type Weekday } from "$lib/course-facets";

  let {
    days = "",
    match = "within",
    onDays,
    onMatch,
  }: {
    days?: string;
    match?: DayMatch;
    onDays: (days: string) => void;
    onMatch: (match: string) => void;
  } = $props();

  const labels: Record<Weekday, string> = {
    mon: "Mon",
    tue: "Tue",
    wed: "Wed",
    thu: "Thu",
    fri: "Fri",
    sat: "Sat",
    sun: "Sun",
  };
  let selected = $derived(
    days
      .split(",")
      .map((day) => day.trim())
      .filter(Boolean),
  );

  function toggle(day: Weekday) {
    const next = selected.includes(day)
      ? selected.filter((item) => item !== day)
      : [...selected, day];
    onDays(weekdays.filter((item) => next.includes(item)).join(","));
  }
</script>

<fieldset class="m-0 min-w-0 border-0 p-0">
  <legend class="mb-2 text-[12px] text-muted">Days</legend>
  <div class="flex flex-wrap gap-1.5" role="group" aria-label="Days">
    {#each weekdays as day (day)}
      <button
        class="min-h-8 border border-border bg-surface px-2 text-[12px] text-foreground"
        class:selected={selected.includes(day)}
        type="button"
        aria-pressed={selected.includes(day)}
        onclick={() => toggle(day)}
      >
        {labels[day]}
      </button>
    {/each}
  </div>
  <div class="mt-2">
    <Select
      label="Day match"
      value={match}
      options={[
        { value: "within", label: "Only these days" },
        { value: "any", label: "Any selected day" },
      ]}
      onChange={onMatch}
    />
  </div>
</fieldset>

<style>
  .selected {
    border-color: var(--accent);
    color: var(--accent);
  }
  button {
    font: inherit;
  }
</style>
