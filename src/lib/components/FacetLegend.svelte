<script lang="ts">
  let { pending = false }: { pending?: boolean } = $props();
</script>

<div class="facet-legend" role="status">
  <span class="matched" title="Courses matching every active filter"
    >Matching</span
  >
  <span
    class="available"
    title="Available courses with the other filters held fixed">Available</span
  >
  <span class="progress">{pending ? "Updating…" : ""}</span>
</div>

<style>
  .facet-legend {
    display: flex;
    align-items: center;
    gap: 14px;
    min-height: 22px;
    font-size: 11px;
    line-height: 16px;
    color: var(--muted);
  }
  .matched,
  .available {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
  }
  .matched::before,
  .available::before {
    content: "";
    width: 10px;
    height: 5px;
    background: var(--accent);
  }
  .available::before {
    background: var(--muted);
    opacity: 0.35;
  }
  .progress {
    margin-left: auto;
    min-width: 58px;
    font-size: 10px;
    text-align: right;
  }
</style>
