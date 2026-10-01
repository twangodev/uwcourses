<script lang="ts">
  import FacetCounts from "./FacetCounts.svelte";
  import FacetBar from "./FacetBar.svelte";
  import InfoTooltip from "./InfoTooltip.svelte";
  import { Chart, Svg } from "layerchart";
  import { scaleBand, scaleLinear } from "d3-scale";
  import type { Snippet } from "svelte";
  import type { FacetBin } from "$lib/facet-distributions";
  let {
    bins,
    label,
    selected = [],
    onPick,
    row,
    histogram = false,
    ready = true,
    maxCount = 0,
    interval,
  }: {
    bins: FacetBin[];
    label: string;
    selected?: string[];
    onPick?: (value: string) => void;
    row?: Snippet<[FacetBin]>;
    histogram?: boolean;
    ready?: boolean;
    maxCount?: number;
    interval?: number;
  } = $props();
  let maximum = $derived(
    Math.max(1, maxCount, ...bins.map((bin) => bin.count)),
  );
  const ticks = $derived([...new Set([0, Math.round(maximum / 2), maximum])]);
  const axisTicks = $derived.by(() => {
    if (!interval || !bins.length) return [];
    const start = Number(bins[0].value);
    const end = Number(bins.at(-1)!.value) + interval;
    const span = end - start;
    return [
      start,
      ...scaleLinear()
        .domain([start, end])
        .ticks(5)
        .filter((tick) => tick > start + span / 8 && tick < end - span / 8),
      end,
    ].map((tick) => ({
      label: tick.toFixed(1),
      position: ((tick - start) / span) * 100,
    }));
  });
</script>

{#if bins.length || !ready}
  <div
    class="facet-chart"
    class:histogram
    aria-busy={!ready}
    aria-label={`${label} distribution`}
  >
    <div class="plot" class:ready aria-hidden="true">
      {#if bins.length}<Chart
          data={bins}
          x={histogram ? "value" : "count"}
          y={histogram ? "count" : "value"}
          xScale={histogram ? scaleBand().padding(0.15) : undefined}
          yScale={histogram ? undefined : scaleBand()}
          xDomain={histogram ? bins.map((bin) => bin.value) : [0, maximum]}
          yDomain={histogram ? [0, maximum] : bins.map((bin) => bin.value)}
          height={histogram ? 108 : bins.length * 36}
          padding={histogram ? { left: 32, top: 8 } : { left: 8, right: 8 }}
          tooltipContext={false}
        >
          {#snippet children({ context })}
            <Svg pointerEvents={false}>
              {#if histogram}
                {#each ticks as tick}
                  <line
                    x1="0"
                    x2={context.width}
                    y1={context.yScale(tick)}
                    y2={context.yScale(tick)}
                    stroke="var(--border)"
                  />
                  <text
                    x="-6"
                    y={context.yScale(tick)}
                    dy={tick === maximum ? "0.8em" : "-0.2em"}
                    text-anchor="end"
                    fill="var(--muted)"
                    font-size="10"
                  >
                    {new Intl.NumberFormat("en-US", {
                      notation: "compact",
                      maximumFractionDigits: 1,
                    }).format(tick)}
                  </text>
                {/each}
              {/if}
              {#each bins as bin (bin.value)}
                {#if histogram}
                  <FacetBar
                    value={bin.value}
                    vertical
                    x={context.xScale(bin.value)}
                    y={context.yScale(bin.count)}
                    width={context.xScale.bandwidth?.() ?? 0}
                    height={context.yScale(0) - context.yScale(bin.count)}
                    fill="var(--muted)"
                    opacity={0.18}
                  />
                  <FacetBar
                    value={bin.value}
                    vertical
                    x={context.xScale(bin.value)}
                    y={context.yScale(bin.matched)}
                    width={context.xScale.bandwidth?.() ?? 0}
                    height={context.yScale(0) - context.yScale(bin.matched)}
                    fill="var(--accent)"
                    opacity={0.8}
                  />
                {:else}
                  <FacetBar
                    value={bin.value}
                    x={0}
                    y={context.yScale(bin.value) + 28}
                    width={context.xScale(bin.count)}
                    height={4}
                    fill="var(--muted)"
                    opacity={0.15}
                  />
                  <FacetBar
                    value={bin.value}
                    x={0}
                    y={context.yScale(bin.value) + 28}
                    width={context.xScale(bin.matched)}
                    height={4}
                    fill="var(--accent)"
                  />
                {/if}
              {/each}
            </Svg>
          {/snippet}
        </Chart>{:else}<span class="placeholder">No distribution yet</span>{/if}
    </div>
    {#if histogram}
      <div
        class="histogram-hover"
        style={`grid-template-columns: repeat(${bins.length || 1}, minmax(0, 1fr))`}
      >
        {#each bins as bin (bin.value)}
          <InfoTooltip
            label={`${label}: ${bin.label}`}
            triggerClass="facet-bin-trigger"
            pressed={onPick ? selected.includes(bin.value) : undefined}
            disabled={bin.disabled || !ready}
            onclick={onPick ? () => onPick(bin.value) : undefined}
          >
            {#snippet trigger()}<span class="sr-only">{bin.label}</span
              >{/snippet}
            <strong class="tooltip-label">{bin.label}</strong>
            <div class="tooltip-count">
              <span>Matching</span><strong class="accent"
                >{bin.matched.toLocaleString()}</strong
              >
            </div>
            <div class="tooltip-count">
              <span>Available</span><strong>{bin.count.toLocaleString()}</strong
              >
            </div>
            {#if onPick}<p class="tooltip-hint">
                {selected.includes(bin.value)
                  ? "Click again to clear this range."
                  : "Click to select this range."}
              </p>{/if}
          </InfoTooltip>
        {/each}
      </div>
      <div
        class="histogram-axis"
        class:interval-axis={interval !== undefined}
        style={`grid-template-columns: repeat(${bins.length || 1}, minmax(0, 1fr))`}
      >
        {#if interval}
          <div class="numeric-axis">
            {#each axisTicks as tick}<span style:left={`${tick.position}%`}
                >{tick.label}</span
              >{/each}
          </div>
        {:else}{#each bins as bin, index}<span
              >{index % Math.max(1, Math.ceil(bins.length / 8)) === 0 ||
              index === bins.length - 1
                ? index === bins.length - 1 && bin.label.includes("–")
                  ? bin.label
                  : bin.value
                : ""}</span
            >{/each}{/if}
      </div>
      <details class="bin-details">
        <summary
          >{interval
            ? `${interval.toFixed(1)}-point intervals`
            : "Counts by value"}</summary
        >
        <div class="chart-rows">
          {#each bins as bin (bin.value)}
            {#if onPick}<button
                type="button"
                aria-label={bin.label}
                aria-pressed={selected.includes(bin.value)}
                disabled={bin.disabled || !ready}
                onclick={() => onPick?.(bin.value)}
              >
                <span class="row-label">{bin.label}</span><FacetCounts
                  count={bin.count}
                  matched={bin.matched}
                  {ready}
                />
              </button>{:else}<span class="bin"
                ><span class="row-label">{bin.label}</span><FacetCounts
                  count={bin.count}
                  matched={bin.matched}
                  {ready}
                /></span
              >{/if}{/each}
        </div>
      </details>
    {:else}
      <div class="chart-rows">
        {#each bins as bin (bin.value)}
          {#if row}{@render row(bin)}
          {:else if onPick}
            <button
              type="button"
              aria-label={bin.label}
              aria-pressed={selected.includes(bin.value)}
              disabled={bin.disabled}
              title={`${bin.label}: ${bin.matched.toLocaleString()} current / ${bin.count.toLocaleString()} available courses`}
              onclick={() => onPick?.(bin.value)}
              ><span class="row-label">{bin.label}</span><FacetCounts
                count={bin.count}
                matched={bin.matched}
                {ready}
              /></button
            >
          {:else}
            <span
              class="bin"
              title={`${bin.label}: ${bin.matched.toLocaleString()} current / ${bin.count.toLocaleString()} available courses`}
              ><span class="row-label">{bin.label}</span><FacetCounts
                count={bin.count}
                matched={bin.matched}
                {ready}
              /></span
            >
          {/if}
        {/each}
      </div>
    {/if}
  </div>
{:else}
  <p class="empty-distribution">No recorded values for these results.</p>
{/if}

<style>
  .facet-chart {
    position: relative;
    width: 100%;
    min-width: 0;
  }
  .plot {
    position: absolute;
    inset: 0;
    pointer-events: none;
    opacity: var(--chart-opacity, 1);
  }
  .chart-rows {
    position: relative;
  }
  .facet-chart:not(.histogram) .plot {
    z-index: 1;
  }
  button,
  .bin {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    width: 100%;
    height: 36px;
    min-height: 36px;
    box-sizing: border-box;
    padding: 0 8px 10px;
    border: 0;
    border-radius: var(--radius-control);
    background: transparent;
    font-size: 12px;
    text-align: left;
  }
  .row-label {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  button[aria-pressed="true"] {
    color: var(--accent);
    background: var(--accent-soft);
  }
  button:focus-visible {
    outline-offset: -2px;
  }
  button:hover {
    background: color-mix(in srgb, var(--bg) 60%, transparent);
  }
  .histogram .plot {
    position: relative;
    height: 108px;
  }
  .histogram-hover {
    display: grid;
    position: absolute;
    top: 0;
    left: 32px;
    width: calc(100% - 32px);
    height: 108px;
  }
  .histogram-axis {
    display: grid;
    text-align: center;
    color: var(--muted);
    font-size: 10px;
    padding-top: 4px;
    height: 20px;
    min-height: 20px;
    align-items: center;
    padding-left: 32px;
  }
  .bin-details {
    border: 0;
    padding: 7px 0 0;
  }
  .interval-axis {
    display: block;
  }
  .numeric-axis {
    position: relative;
    height: 16px;
  }
  .numeric-axis span {
    position: absolute;
    transform: translateX(-50%);
    white-space: nowrap;
  }
  .numeric-axis span:first-child {
    transform: none;
  }
  .numeric-axis span:last-child {
    transform: translateX(-100%);
  }
  .bin-details summary {
    font-size: 11px;
    font-weight: 400;
    color: var(--muted);
  }
  .chart-rows :global(.course-select-item) {
    height: 36px;
    box-sizing: border-box;
    padding-top: 0;
    padding-bottom: 10px;
  }
  .placeholder {
    display: grid;
    place-items: center;
    height: 108px;
    color: var(--muted);
    font-size: 11px;
    border-radius: 4px;
    background: color-mix(in srgb, var(--muted) 5%, transparent);
  }
  .bin-details .chart-rows {
    max-height: 220px;
    overflow-y: auto;
  }
  .empty-distribution {
    font-size: 12px;
    color: var(--muted);
  }
  .histogram-hover :global(.facet-bin-trigger) {
    height: 108px;
    width: 100%;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
  }
  .histogram-hover :global(.facet-bin-trigger:hover),
  .histogram-hover :global(.facet-bin-trigger:focus-visible) {
    background: color-mix(in srgb, var(--accent) 7%, transparent);
    outline-offset: -2px;
  }
  .tooltip-label {
    display: block;
    margin-bottom: 8px;
    font-weight: 550;
  }
  .tooltip-count {
    display: flex;
    justify-content: space-between;
    gap: 36px;
    font-variant-numeric: tabular-nums;
  }
  .tooltip-count span {
    color: var(--muted);
  }
  .tooltip-count strong {
    font-weight: 500;
  }
  .histogram-hover :global(.facet-bin-trigger[aria-pressed="true"]) {
    background: color-mix(in srgb, var(--accent) 8%, transparent);
    box-shadow: inset 0 -2px 0 var(--accent);
  }
  .tooltip-hint {
    color: var(--muted);
    font-size: 12px;
    margin-top: 10px;
  }
  @media (prefers-reduced-motion: no-preference) {
    .plot {
      transition: opacity var(--motion-normal) var(--motion-ease);
    }
    .plot.ready {
      animation: chart-arrive var(--motion-enter) var(--motion-ease);
    }
    @keyframes chart-arrive {
      from {
        opacity: 0;
      }
    }
  }
</style>
