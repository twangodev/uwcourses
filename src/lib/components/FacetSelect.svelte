<script lang="ts">
  import Select, { type SelectOption } from "./Select.svelte";
  import FacetChart from "./FacetChart.svelte";
  import FacetCounts from "./FacetCounts.svelte";
  import FacetLegend from "./FacetLegend.svelte";
  import {
    facetOptionBins,
    type FacetDistribution,
    type FacetOption,
  } from "$lib/facet-distributions";
  let {
    value = $bindable(""),
    options,
    label,
    onChange,
    onOpenChange,
    distribution,
    pending = false,
    error = "",
  }: {
    value?: string;
    options: FacetOption[];
    label: string;
    onChange?: (value: string) => void;
    onOpenChange?: (open: boolean) => void;
    distribution?: FacetDistribution;
    pending?: boolean;
    error?: string;
  } = $props();
  const ready = $derived(distribution !== undefined);
  const bins = $derived([
    ...facetOptionBins(
      options.filter((option) => option.value && !option.value.includes(",")),
      distribution,
    ),
    ...(distribution?.bins.filter(
      (bin) =>
        bin.disabled && !options.some((option) => option.value === bin.value),
    ) ?? []),
  ]);
  const summaries = $derived(
    options
      .filter((option) => !option.value || option.value.includes(","))
      .map((option) => ({
        ...option,
        count: option.value
          ? (distribution?.matched ?? 0)
          : (distribution?.total ?? 0),
        matched: distribution?.matched ?? 0,
      })),
  );
  const rows = $derived(
    [...summaries, ...bins].map((bin) => ({
      ...bin,
      title: ready
        ? `${bin.label}: ${bin.matched.toLocaleString()} matching / ${bin.count.toLocaleString()} available courses`
        : undefined,
    })),
  );
  const counts = $derived(new Map(rows.map((row) => [row.value, row])));
</script>

<Select bind:value options={rows} {label} {onChange} {onOpenChange}>
  {#snippet header()}
    <FacetLegend {pending} />
    {#if error}<p role="alert" class="error">{error}</p>{/if}
  {/snippet}
  {#snippet optionContent(option: SelectOption)}
    <span class="option-label">{option.label}</span>
    <span class="option-counts"
      ><FacetCounts
        count={counts.get(option.value)?.count ?? 0}
        matched={counts.get(option.value)?.matched ?? 0}
        {ready}
      /></span
    >
  {/snippet}
  {#snippet children(renderOption)}
    {#each summaries as option (option.value)}{@render renderOption(
        option,
      )}{/each}
    <FacetChart {label} {bins} {ready}>
      {#snippet row(bin)}{@render renderOption({
          ...bin,
          title: counts.get(bin.value)?.title,
        })}{/snippet}
    </FacetChart>
  {/snippet}
</Select>

<style>
  .option-counts {
    display: flex;
    justify-content: end;
    min-width: 72px;
    flex-shrink: 0;
  }
  .option-label {
    min-width: 0;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .error {
    color: var(--accent);
    font-size: 11px;
    line-height: 16px;
    margin: 4px 0;
  }
</style>
