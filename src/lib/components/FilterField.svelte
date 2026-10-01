<script lang="ts">
  import type { Snippet } from "svelte";
  let {
    label,
    missing = 0,
    children,
  }: { label: string; missing?: number; children: Snippet } = $props();
</script>

<fieldset class="filter-field">
  <legend>{label}</legend>
  {@render children()}
  {#if missing}<p class="missing">
      {missing.toLocaleString()}
      {missing === 1 ? "course" : "courses"} without recorded values
    </p>{/if}
</fieldset>

<style>
  .filter-field {
    width: 100%;
    border: 0;
    padding: 0;
    margin: 0;
    min-width: 0;
  }
  legend {
    color: var(--text);
    font-size: 12px;
    font-weight: 550;
    margin-bottom: 8px;
  }
  .missing {
    color: var(--muted);
    font-size: 11px;
    margin-top: 8px;
  }
</style>
