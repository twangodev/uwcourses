<script lang="ts">
  import type { Snippet } from "svelte";
  import FilterField from "./FilterField.svelte";
  import { facetOptionBins } from "$lib/facet-distributions";
  import { tokens } from "$lib/course-filter-ui";
  import FacetChart from "./FacetChart.svelte";
  import type {
    FacetDistribution,
    FacetOption,
  } from "$lib/facet-distributions";
  let {
    label,
    value = "",
    options,
    onChange,
    distribution,
    multiple = true,
    presets,
    columns = 1,
  }: {
    label: string;
    value?: string;
    options: FacetOption[];
    onChange: (value: string) => void;
    distribution?: FacetDistribution;
    multiple?: boolean;
    presets?: Snippet;
    columns?: 1 | 2;
  } = $props();
  let selected = $derived(tokens(value));
  const bins = $derived(facetOptionBins(options, distribution));
  const groups = $derived(
    columns === 2
      ? [
          bins.slice(0, Math.ceil(bins.length / 2)),
          bins.slice(Math.ceil(bins.length / 2)),
        ]
      : [bins],
  );
  const maxCount = $derived(Math.max(1, ...bins.map((bin) => bin.count)));
  function toggle(token: string) {
    if (!multiple) {
      onChange(selected.includes(token) ? "" : token);
      return;
    }
    const next = selected.includes(token)
      ? selected.filter((item) => item !== token)
      : [...selected, token];
    onChange(next.join(","));
  }
</script>

<FilterField {label} missing={distribution?.missing}>
  {#if presets}<div class="presets">{@render presets()}</div>{/if}
  <div
    class="choice-charts"
    style={`--choice-columns: ${columns}`}
  >
    {#each groups as group, index (index)}
      <FacetChart
        {label}
        bins={group}
        {selected}
        {maxCount}
        onPick={toggle}
        ready={distribution !== undefined}
      />
    {/each}
  </div>
</FilterField>

<style>
  .choice-charts {
    display: grid;
    grid-template-columns: repeat(var(--choice-columns), minmax(0, 1fr));
    gap: 16px;
    width: 100%;
  }
  .presets {
    margin-bottom: 8px;
  }
  @media (max-width: 600px) {
    .choice-charts {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
