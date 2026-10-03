<script lang="ts">
  import { departmentName } from "$lib/departments";
  import { ArrowUpRight, Search } from "@lucide/svelte";
  import SearchInput from "$lib/components/SearchInput.svelte";
  import CampusScene from "$lib/components/CampusScene.svelte";
  import CampusMap from "$lib/components/CampusMap.svelte";
  import { campusIntensity, type CampusDay } from "$lib/campus";
  import { hasOfficialBuildings } from "$lib/campus-buildings";
  let activity = $state<{ day: CampusDay | null; now: number } | null>(null);
  let { data } = $props();
  let peak = $derived(data.campus.maxConcurrentClasses);
  let heatTicks = $derived([...new Set([0, Math.round(peak / 4), peak])]);
  let departments = $derived(
    [...data.status.departments].sort((a, b) => b.count - a.count).slice(0, 8),
  );
</script>

<section
  class="relative isolate pt-7.5 pb-10 landing px-0"
  aria-labelledby="landing-title"
>
  <CampusMap
    maxConcurrentClasses={peak}
    day={activity?.day}
    now={activity?.now}
  />
  <CampusScene
    coverage={data.campus}
    onactivity={(day, now) => (activity = { day, now })}
  />
  <div class="relative z-2 w-[min(100%,_580px)] m-0 landing-copy">
    <h1 class="text-[22px] font-medium tracking-[-0.035em]" id="landing-title">
      Search UW–Madison courses
    </h1>
    <p class="text-[13px] text-muted mt-1.5 search-description">
      Compare grades, prerequisites, and professor reviews.
    </p>
    <form
      action="/search"
      class="flex items-center gap-3 pr-[7px] pl-4 border border-border rounded-[6px] mt-3 bg-canvas w-full landing-search py-[7px]"
    >
      <SearchInput
        revision={data.status.revision}
        label="Search courses or topics"
        placeholder="A course, professor, or topic…"
      />
      <button
        class="inline-flex items-center justify-start gap-2 shrink-0 min-h-10.5 text-[14px] bg-transparent text-foreground border-0 py-2 px-2.5"
        aria-label="Find courses"><Search size={19} strokeWidth={1.5} /></button
      >
    </form>
    <div class="flex justify-start gap-4.5 mt-3.5 text-[13px] try-search">
      <span class="text-muted">Try</span><a
        class="underline [text-underline-offset:4px]"
        href="/courses/COMPSCI_300">CS 300</a
      ><a class="underline [text-underline-offset:4px]" href="/search?q=climate"
        >climate</a
      ><a class="underline [text-underline-offset:4px]" href="/search?q=film"
        >film</a
      >
    </div>
  </div>
  <div
    class="relative z-1 flex justify-start items-center flex-wrap gap-3 mt-6 text-muted text-[10px] map-caption"
  >
    <span
      class="inline-flex items-center gap-2"
      title="Heat shows concurrent scheduled class meetings at buildings with recorded coordinates, not live attendance. Missing locations and ambiguous building matches are omitted."
      >Scheduled classes by building</span
    >
    <div
      class="w-25 heat-legend my-0 mx-1.5"
      aria-label={`Square-root color scale: 0 to ${peak} concurrent classes per building. Reference fixed across the published schedule.`}
    >
      <div class="h-[5px] rounded-[3px] heat-ramp"></div>
      <div class="relative h-3 mt-1 text-[9px] heat-ticks">
        {#each heatTicks as tick}<span
            class="absolute"
            style:left={`${campusIntensity(tick, peak) * 100}%`}>{tick}</span
          >{/each}
      </div>
    </div>
    {#if hasOfficialBuildings}<a href="https://map.wisc.edu/buildings/"
        >Buildings: UW campus map</a
      >{/if}
    <a
      class="block w-fit mr-0 ml-auto text-[9px] text-muted no-underline map-credit my-0"
      href="https://www.openstreetmap.org/copyright"
      >© OpenStreetMap contributors</a
    >
  </div>
</section>
<div
  class="flex justify-between gap-4 border-y border-y-border text-[14px] campus-strip py-[21px] px-0"
>
  <span
    >{data.status.courses.toLocaleString()} courses. Plenty of possibilities.</span
  ><a class="inline-flex items-center gap-[7px]" href="/search"
    >Explore all courses <ArrowUpRight size={15} /></a
  >
  <a class="inline-flex items-center gap-[7px]" href="/stats"
    >Campus by the numbers <ArrowUpRight size={15} /></a
  >
</div>
<section
  class="grid grid-cols-[1fr_2fr] gap-16 pt-10.5 pb-2.5 discover px-0"
  aria-labelledby="discover-title"
>
  <div class="discover-intro">
    <h2 class="text-[25px]" id="discover-title">Browse departments</h2>
    <a
      class="inline-flex items-center gap-[7px] mt-6 text-[13px]"
      href="/departments">All departments <ArrowUpRight size={14} /></a
    >
  </div>
  <div class="grid grid-cols-[1fr_1fr] gap-x-9 department-list">
    {#each departments as d}<a
        class="flex justify-between items-center gap-3 border-b border-b-border text-[14px] py-[17px] px-0"
        href={"/departments/" + encodeURIComponent(d.subject)}
        ><span>{departmentName(d.subject)}</span><span
          class="inline-flex items-center gap-3 text-muted whitespace-nowrap department-count"
          >{d.count} courses <ArrowUpRight size={14} /></span
        ></a
      >{/each}
  </div>
</section>

<style>
  .heat-ramp {
    background: linear-gradient(
      to right,
      transparent,
      color-mix(in srgb, var(--accent) 8%, transparent) 0.1%,
      color-mix(in srgb, var(--accent) 38%, transparent)
    );
  }
  .heat-ticks span {
    transform: translateX(-50%);
  }
  .landing-search:focus-within {
    border-color: var(--accent);
  }
  button:hover {
    opacity: 0.85;
  }
  .try-search a {
    text-decoration-color: var(--border);
  }
  .department-count {
    font: 11px var(--font-sans);
  }
  @media (max-width: 760px) {
    .landing {
      padding: 20px 0 24px;
    }
    .campus-strip {
      font-size: 13px;
      flex-wrap: wrap;
    }
    .discover {
      grid-template-columns: 1fr;
      gap: 24px;
      padding-top: 28px;
    }
    .department-list {
      column-gap: 20px;
    }
    .department-list a {
      align-items: start;
      flex-direction: column;
      gap: 5px;
    }
  }
  @media (prefers-reduced-motion: no-preference) {
    .landing-copy {
      animation: landing-arrive var(--motion-travel) var(--motion-ease) both;
    }
    .landing-search button :global(svg) {
      transition: transform 180ms ease;
    }
    .landing-search button:hover :global(svg) {
      transform: translate(2px, -2px);
    }
    @keyframes landing-arrive {
      from {
        opacity: 0;
        transform: translateY(6px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }
  }
</style>
