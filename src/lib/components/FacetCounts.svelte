<script lang="ts">
  import AnimatedNumber from "./AnimatedNumber.svelte";
  let {
    count,
    matched,
    ready = true,
  }: { count: number; matched: number; ready?: boolean } = $props();
</script>

<span
  class="facet-counts"
  class:ready
  aria-label={ready
    ? `${matched.toLocaleString()} matching / ${count.toLocaleString()} available courses`
    : "Distribution not loaded"}
>
  {#if ready}<span class="matched"><AnimatedNumber value={matched} /></span
    ><span class="separator">/</span><span
      ><AnimatedNumber value={count} /></span
    >{:else}<span class="count-skeleton" aria-hidden="true"></span>{/if}
</span>

<style>
  .facet-counts {
    display: inline-flex;
    align-items: center;
    justify-content: end;
    gap: 4px;
    flex-shrink: 0;
    min-width: 48px;
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    color: var(--muted);
  }
  .matched {
    color: var(--accent);
  }
  .separator {
    opacity: 0.6;
  }
  .count-skeleton {
    width: 38px;
    height: 8px;
    border-radius: var(--radius-control);
    background: var(--border);
  }
  @media (prefers-reduced-motion: no-preference) {
    .ready {
      animation: counts-arrive var(--motion-enter) var(--motion-ease);
    }
    @keyframes counts-arrive {
      from {
        opacity: 0;
      }
    }
    .count-skeleton {
      animation: count-pulse 1.4s ease-in-out infinite alternate;
    }
    @keyframes count-pulse {
      to {
        opacity: 0.45;
      }
    }
  }
</style>
