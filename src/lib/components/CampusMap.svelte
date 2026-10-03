<script lang="ts">
  import { X } from "@lucide/svelte";
  import AnimatedNumber from "./AnimatedNumber.svelte";
  import { courseUrl } from "$lib/format";
  import { madisonZone } from "$lib/campus";
  import { buildingOutlines } from "$lib/campus-buildings";
  import map from "$lib/assets/campus-map.svg";
  import { campusHeat, campusIntensity, type CampusDay } from "$lib/campus";
  let {
    maxConcurrentClasses,
    day = null,
    now = null,
  }: {
    maxConcurrentClasses: number;
    day?: CampusDay | null;
    now?: number | null;
  } = $props();
  let heat = $derived(
    now !== null ? buildingOutlines(campusHeat(day, now, true)) : [],
  );
  let selected = $state<string | null>(null);
  let pinned = $state(false);
  const tooltipId = $props.id();
  let cursor = $state<{ x: number; y: number } | null>(null);
  let viewportWidth = $state(0);
  let viewportHeight = $state(0);
  let panelWidth = $state(350);
  let panelHeight = $state(0);
  const gutter = 12;
  const offset = 16;
  let floating = $derived(cursor !== null && viewportWidth > 700);
  let panelX = $derived(
    cursor
      ? Math.max(
          gutter,
          Math.min(
            cursor.x + offset + panelWidth > viewportWidth - gutter
              ? cursor.x - panelWidth - offset
              : cursor.x + offset,
            viewportWidth - panelWidth - gutter,
          ),
        )
      : 0,
  );
  let panelY = $derived(
    cursor
      ? Math.max(
          gutter,
          Math.min(
            cursor.y + offset,
            viewportHeight - panelHeight - gutter - 1,
          ),
        )
      : 0,
  );
  function followPointer(event: PointerEvent, id: string) {
    if (
      !pinned &&
      event.pointerType === "mouse" &&
      matchMedia("(hover: hover) and (min-width: 701px)").matches
    ) {
      selected = id;
      cursor = { x: event.clientX, y: event.clientY };
    }
  }
  function selectBuilding(id: string) {
    pinned = true;
    selected = id;
  }
  function dismiss() {
    selected = null;
    pinned = false;
    cursor = null;
  }
  let building = $derived(heat.find((b) => b.id === selected));
  let sessions = $derived(
    (day?.buildings ?? [])
      .filter((b) => building?.names.includes(b.name))
      .flatMap((b) => b.sessions ?? [])
      .sort((a, b) => a.startsAt - b.startsAt),
  );
  let active = $derived(
    sessions.filter((s) => now !== null && s.startsAt <= now && s.endsAt > now),
  );
  let known = $derived(active.filter((s) => s.enrolled !== null));
  let students = $derived(
    building?.count === 0
      ? 0
      : known.length
        ? known.reduce((total, s) => total + s.enrolled!, 0)
        : null,
  );
  let rooms = $derived(new Set(active.map((s) => s.room).filter(Boolean)).size);
  const time = (at: number) =>
    new Intl.DateTimeFormat("en-US", {
      timeZone: madisonZone,
      hour: "numeric",
      minute: "2-digit",
    }).format(at);
</script>

<svelte:window
  bind:innerWidth={viewportWidth}
  bind:innerHeight={viewportHeight}
  onkeydown={(event) => {
    if (event.key === "Escape") dismiss();
  }}
  onclick={(event) => {
    if (
      event.target instanceof Element &&
      !event.target.closest(".building-panel, .building-heat")
    )
      dismiss();
  }}
/>
<div class="absolute inset-0 pointer-events-none campus-map">
  <div class="absolute inset-0 map-art">
    <svg
      class="block w-full h-full"
      viewBox="0 0 900 505"
      preserveAspectRatio="xMidYMid slice"
    >
      <image
        class="opacity-[0.35] base-map"
        href={map}
        width="900"
        height="505"
      />
      {#each heat as building (building.id)}
        <path
          class="pointer-events-auto cursor-pointer opacity-[0.75] building-heat"
          d={building.path}
          fill-rule="evenodd"
          fill="var(--accent)"
          fill-opacity={building.count
            ? 0.08 + campusIntensity(building.count, maxConcurrentClasses) * 0.3
            : 0}
          stroke="var(--accent)"
          stroke-opacity={building.count
            ? 0.45 +
              campusIntensity(building.count, maxConcurrentClasses) * 0.55
            : 0.14}
          stroke-width="1.25"
          stroke-linejoin="round"
          vector-effect="non-scaling-stroke"
          role="button"
          tabindex="0"
          aria-label={`${building.name}: ${building.count} classes in session`}
          aria-expanded={pinned && selected === building.id}
          aria-describedby={!pinned && selected === building.id
            ? tooltipId
            : undefined}
          onpointerenter={(event) => followPointer(event, building.id)}
          onpointermove={(event) => {
            if (selected === building.id) followPointer(event, building.id);
          }}
          onpointerleave={() => {
            if (!pinned) dismiss();
          }}
          onblur={() => {
            if (!pinned) dismiss();
          }}
          onfocus={(event) => {
            if (!pinned && event.currentTarget.matches(":focus-visible")) {
              const rect = event.currentTarget.getBoundingClientRect();
              selected = building.id;
              cursor = { x: rect.right, y: rect.top };
            }
          }}
          onclick={() => selectBuilding(building.id)}
          onkeydown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              selectBuilding(building.id);
            }
          }}
          data-building={building.name}
          data-meetings={building.count}
        />
      {/each}
    </svg>
  </div>
  {#if building}
    <section
      class="absolute z-4 top-17 right-5 w-[min(350px,_calc(100%_-_32px))] pointer-events-auto p-5 border border-border rounded-[10px] bg-canvas shadow-[0_16px_48px_#0003] building-panel"
      class:floating
      class:building-tooltip={!pinned}
      id={!pinned ? tooltipId : undefined}
      role={pinned ? "region" : "tooltip"}
      bind:offsetWidth={panelWidth}
      bind:offsetHeight={panelHeight}
      style:left={floating ? `${panelX}px` : undefined}
      style:top={floating ? `${panelY}px` : undefined}
      aria-label={`${building.name} details`}
    >
      <header class="flex justify-between items-start gap-4">
        <div>
          <span class="text-[10px] text-muted eyebrow">In session now</span>
          <h2 class="text-[21px] font-medium tracking-[-0.035em] mt-1">
            {building.name}
          </h2>
        </div>
        {#if pinned}<button
            class="grid place-items-center border-0 bg-transparent text-muted w-7 h-7 cursor-pointer close"
            aria-label="Close building details"
            onclick={dismiss}><X size={17} /></button
          >{/if}
      </header>
      <dl class="grid grid-cols-[1fr_1fr] gap-[15px] my-5.5 mx-0">
        <div>
          <dt class="text-muted text-[11px]">Classes now</dt>
          <dd class="text-[25px] tracking-[-0.04em] mt-1 mb-0 mx-0">
            <AnimatedNumber value={building.count} />
          </dd>
        </div>
        <div>
          <dt class="text-muted text-[11px]">Recorded enrollment</dt>
          <dd class="text-[25px] tracking-[-0.04em] mt-1 mb-0 mx-0">
            <AnimatedNumber value={students} />
          </dd>
        </div>
        {#if pinned}<div>
            <dt class="text-muted text-[11px]">Rooms in use</dt>
            <dd class="text-[25px] tracking-[-0.04em] mt-1 mb-0 mx-0">
              <AnimatedNumber value={sessions.length ? rooms : null} />
            </dd>
          </div>
          <div>
            <dt class="text-muted text-[11px]">Meetings today</dt>
            <dd class="text-[25px] tracking-[-0.04em] mt-1 mb-0 mx-0">
              <AnimatedNumber value={sessions.length || null} />
            </dd>
          </div>{/if}
      </dl>
      {#if !pinned}
        <div class="text-[12px] leading-[1.7] tooltip-classes">
          {#each active.slice(0, 3) as session}
            <p>
              {session.courses
                .map((course) => course.code)
                .join(" / ")}{session.room ? ` · Room ${session.room}` : ""}
            </p>
          {/each}
          {#if active.length > 3}<p>+{active.length - 3} more classes</p>{/if}
        </div>
        <p class="text-muted text-[11px] leading-[1.5] mt-4 note">
          Scheduled enrollment, not live attendance.
        </p>
        <p class="mt-2 text-[11px] text-muted tooltip-hint">
          Click for class details
        </p>
      {:else}
        <div class="max-h-52.5 overflow-auto overscroll-contain classes">
          {#each active as session}
            <article class="border-t border-t-border py-3 px-0">
              <div class="wrap-anywhere text-[13px] class-codes">
                {#each session.courses as course, i}{#if i}<span>
                      /
                    </span>{/if}<a
                    class="text-foreground [text-underline-offset:3px]"
                    href={courseUrl(course.code)}>{course.code}</a
                  >{/each}
              </div>
              <p class="mt-1 mb-0 text-muted text-[11px] leading-[1.5] mx-0">
                {[
                  session.courses[0]?.section ?? "Class",
                  session.room ? `Room ${session.room}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <p class="mt-1 mb-0 text-muted text-[11px] leading-[1.5] mx-0">
                {time(session.startsAt)}–{time(
                  session.endsAt,
                )}{session.enrolled !== null
                  ? ` · ${session.enrolled} enrolled`
                  : ""}
              </p>
              {#if session.instructors.length}<p
                  class="mt-1 mb-0 text-muted text-[11px] leading-[1.5] text-pretty instructors mx-0"
                >
                  {session.instructors.join(", ")}
                </p>{/if}
            </article>
          {:else}<p class="text-muted text-[11px] leading-[1.5] empty">
              {sessions.length
                ? "No classes in session right now."
                : "Class details are unavailable in this schedule snapshot."}
            </p>{/each}
        </div>
        <p class="text-muted text-[11px] leading-[1.5] mt-4 note">
          Published schedule and enrollment, not live attendance.{#if known.length < active.length}{" "}
            Enrollment is missing for {active.length - known.length} active {active.length -
              known.length ===
            1
              ? "class"
              : "classes"}.{/if}
        </p>
      {/if}
    </section>
  {/if}
</div>

<style>
  /* Feather the map without fading the interactive details panel. */
  .map-art {
    mask-image:
      linear-gradient(
        to right,
        transparent,
        #0004 4%,
        #000b 9%,
        #000 16%,
        #000 84%,
        #000b 91%,
        #0004 96%,
        transparent
      ),
      linear-gradient(
        to bottom,
        transparent,
        #0004 9%,
        #000b 17%,
        #000 26%,
        #000 66%,
        #000b 78%,
        #0004 90%,
        transparent
      );
    mask-composite: intersect;
  }
  :global(.dark) .base-map {
    filter: invert(1);
    opacity: 0.24;
  }

  .building-heat:hover,
  .building-heat:focus-visible {
    stroke-opacity: 1;
    stroke-width: 2;
    fill-opacity: 0.4;
    outline: none;
  }
  .building-panel.floating {
    position: fixed;
    right: auto;
    width: min(350px, calc(100vw - 24px));
    max-height: calc(100dvh - 24px);
    overflow-y: auto;
  }
  .building-panel.building-tooltip {
    width: min(280px, calc(100vw - 24px));
    padding: 14px 16px;
    pointer-events: none;
  }
  .building-tooltip h2 {
    font-size: 17px;
  }
  .building-tooltip dl {
    margin: 14px 0;
    gap: 12px;
  }
  .building-tooltip dd {
    font-size: 21px;
  }
  .building-tooltip .note {
    margin-top: 10px;
  }
  @media (max-width: 700px) {
    .building-panel {
      top: 100px;
      right: 16px;
    }
    .classes {
      max-height: 170px;
    }
  }
  @media (prefers-reduced-motion: no-preference) {
    .building-heat {
      pointer-events: auto;
      cursor: pointer;
      transition:
        fill-opacity 800ms ease,
        stroke-opacity 800ms ease;
      animation: heat-in 600ms ease both;
    }
    @keyframes heat-in {
      from {
        opacity: 0;
      }
      to {
        opacity: 0.75;
      }
    }
  }
</style>
