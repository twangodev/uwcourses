<script lang="ts">
  import map from "$lib/assets/campus-map.svg";
  import {
    buildingOutlines,
    hasOfficialBuildings,
  } from "$lib/campus-buildings";
  import { campusIntensity } from "$lib/campus";
  import type { SchoolTerm } from "$lib/school-stats";
  let {
    buildings,
    preview = false,
  }: { buildings: SchoolTerm["schedule"]["buildings"]; preview?: boolean } =
    $props();
  let selected = $state("");
  let outlines = $derived(
    buildingOutlines(
      buildings.map((b) => ({
        name: b.name,
        x: ((b.longitude + 89.425) / 0.034) * 900,
        y: ((43.082 - b.latitude) / 0.014) * 505,
        count: b.enrolledVisits,
      })),
    ),
  );
  let peak = $derived(Math.max(1, ...outlines.map((b) => b.count)));
  let chosen = $derived(outlines.find((b) => b.id === selected));
  let chosenBuildings = $derived(
    buildings.filter((b) => chosen?.names.includes(b.name)),
  );
  let knownMeetings = $derived(
    chosenBuildings.reduce((total, b) => total + b.knownMeetings, 0),
  );
  let meetings = $derived(
    chosenBuildings.reduce((total, b) => total + b.meetings, 0),
  );
</script>

<div class="relative min-w-0 map" class:preview>
  <svg
    class="w-full h-auto block"
    viewBox="0 0 900 505"
    preserveAspectRatio={preview ? "xMidYMid slice" : "xMidYMid meet"}
    aria-label="Scheduled enrollment visits by campus building"
  >
    <image href={map} width="900" height="505" class="opacity-[0.55] base" />
    {#each outlines as b}
      {#if preview}
        <path
          class="cursor-pointer"
          d={b.path}
          fill-rule="evenodd"
          fill="var(--accent)"
          fill-opacity={0.12 + campusIntensity(b.count, peak) * 0.65}
          stroke="var(--accent)"
          stroke-width="0.6"
        />
      {:else}
        <path
          class="cursor-pointer"
          d={b.path}
          fill-rule="evenodd"
          fill="var(--accent)"
          fill-opacity={0.12 + campusIntensity(b.count, peak) * 0.65}
          stroke="var(--accent)"
          stroke-width={selected === b.id ? 2 : 0.6}
          role="button"
          tabindex="0"
          aria-label={`${b.name}: ${b.count.toLocaleString()} scheduled enrollment visits`}
          onclick={() => (selected = b.id)}
          onpointerenter={() => (selected = b.id)}
          onfocus={() => (selected = b.id)}
          onkeydown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              selected = b.id;
            }
          }}
        />
      {/if}
    {/each}
  </svg>
  {#if !preview}<p
      class="min-h-[2.6em] mt-3 mb-0 text-[13px] text-muted caption mx-0"
      aria-live="polite"
    >
      {#if chosen}<strong class="text-foreground font-medium"
          >{chosen.name}</strong
        >
        · {knownMeetings
          ? `${chosen.count.toLocaleString()} scheduled enrollment visits`
          : "Enrollment unavailable"} · {meetings.toLocaleString()} meetings{:else}Select
        a building to explore its teaching activity.{/if}
    </p>
  {/if}
  {#if hasOfficialBuildings}<a
      class="text-[10px] text-muted attribution"
      href="https://map.wisc.edu/buildings/">Buildings: UW campus map</a
    >{/if}
  {#if preview}<span class="text-[10px] text-muted attribution"
      >© OpenStreetMap contributors</span
    >{:else}<a
      class="text-[10px] text-muted attribution"
      href="https://www.openstreetmap.org/copyright"
      >© OpenStreetMap contributors</a
    >{/if}
</div>

<style>
  .map.preview {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .preview svg {
    mask-image: linear-gradient(
      to bottom,
      transparent,
      black 6%,
      black 94%,
      transparent
    );
    flex: 1;
    min-height: 0;
  }
  :global(.dark) .base {
    filter: invert(1);
    opacity: 0.26;
  }
  path {
    transition: fill-opacity 160ms;
  }
  path:focus-visible {
    outline: none;
    stroke: var(--text);
    stroke-width: 3;
  }
  @media (prefers-reduced-motion: reduce) {
    path {
      transition: none;
    }
  }
</style>
