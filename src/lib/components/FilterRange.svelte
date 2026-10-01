<script lang="ts">
  import type { Snippet } from "svelte";
  import FilterField from "./FilterField.svelte";
  import {
    creditHistogramBins,
    gpaHistogramBins,
    histogramBinRange,
    type HistogramRange,
  } from "$lib/facet-distributions";
  import { onDestroy } from "svelte";
  import FacetChart from "./FacetChart.svelte";
  import type { FacetDistribution } from "$lib/facet-distributions";
  let {
    label,
    min = "",
    max = "",
    limit,
    step,
    onChange,
    onRangeChange,
    maxExclusive = false,
    distribution,
    inline = false,
    children,
  }: {
    label: string;
    min?: string;
    max?: string;
    limit: number;
    step: number;
    onChange: (bound: "min" | "max", value: string) => void;
    onRangeChange: (range: HistogramRange) => void;
    maxExclusive?: boolean;
    distribution?: FacetDistribution;
    inline?: boolean;
    children?: Snippet;
  } = $props();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const interval = $derived(limit === 4 ? 0.1 : undefined);
  const selected = $derived(
    (distribution?.bins ?? [])
      .filter((bin) => {
        const range = histogramBinRange(bin.value, limit, interval);
        return (
          min !== "" &&
          max !== "" &&
          Number(min) === Number(range.min) &&
          Number(max) === Number(range.max) &&
          maxExclusive === range.maxExclusive
        );
      })
      .map((bin) => bin.value),
  );
  function pick(value: string) {
    for (const timer of timers.values()) clearTimeout(timer);
    timers.clear();
    onRangeChange(
      selected.includes(value)
        ? { min: "", max: "", maxExclusive: false }
        : histogramBinRange(value, limit, interval),
    );
  }
  onDestroy(() => {
    for (const timer of timers.values()) clearTimeout(timer);
  });
  function update(
    input: HTMLInputElement,
    bound: "min" | "max",
    immediate = false,
  ) {
    clearTimeout(timers.get(bound));
    if (!input.validity.valid) return;
    const value = input.value;
    const apply = () => {
      if (value !== (bound === "min" ? min : max)) onChange(bound, value);
    };
    if (immediate) apply();
    else timers.set(bound, setTimeout(apply, 180));
  }
</script>

<FilterField {label} missing={distribution?.missing}>
  <div class="range-layout" class:inline>
    <FacetChart
      {label}
      bins={limit === 20
        ? creditHistogramBins(distribution?.bins ?? [])
        : gpaHistogramBins(distribution?.bins ?? [])}
      histogram
      {interval}
      {selected}
      onPick={pick}
      ready={distribution !== undefined}
    />
    <div class="range-controls">
      <div class="range">
        <label
          >At least<input
            aria-label={`${label} at least`}
            type="number"
            min="0"
            max={limit}
            {step}
            value={min}
            placeholder="Any"
            oninput={(event) => update(event.currentTarget, "min")}
            onchange={(event) => update(event.currentTarget, "min", true)}
          /></label
        >
        <span aria-hidden="true">–</span>
        <label
          >{maxExclusive ? "Below" : "At most"}<input
            aria-label={`${label} ${maxExclusive ? "below" : "at most"}`}
            type="number"
            min="0"
            max={limit}
            {step}
            value={max}
            placeholder="Any"
            oninput={(event) => update(event.currentTarget, "max")}
            onchange={(event) => update(event.currentTarget, "max", true)}
          /></label
        >
      </div>
      {#if children}{@render children()}{/if}
    </div>
  </div>
</FilterField>

<style>
  .inline {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    align-items: start;
    gap: 24px;
  }
  .range-controls {
    display: grid;
    align-content: start;
    gap: 12px;
    min-width: 0;
  }
  .inline .range {
    margin-top: 0;
  }
  @media (max-width: 600px) {
    .inline {
      grid-template-columns: minmax(0, 1fr);
      gap: 12px;
    }
  }
  .range {
    display: flex;
    align-items: end;
    gap: 10px;
    margin-top: 12px;
  }
  label {
    display: grid;
    gap: 5px;
    font-size: 12px;
    color: var(--muted);
    min-width: 0;
  }
  input {
    width: 110px;
    max-width: 100%;
    min-height: 38px;
    padding: 6px 10px;
    background: var(--bg);
    font-size: 14px;
  }
  .range > span {
    align-self: center;
    padding-top: 18px;
    color: var(--muted);
  }
</style>
