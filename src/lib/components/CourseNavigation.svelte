<script lang="ts">
  import { onMount, type Snippet } from "svelte";
  import {
    BookOpen,
    GitBranch,
    CalendarDays,
    Users,
    ChartColumn,
    Layers,
  } from "@lucide/svelte";
  let {
    code,
    title,
    heading,
    content,
    navigationHeight = $bindable(43),
    children,
  }: {
    code: string;
    title: string;
    heading?: HTMLElement;
    content?: HTMLElement;
    navigationHeight?: number;
    children: Snippet;
  } = $props();
  let container: HTMLDivElement;
  let active = $state("overview");
  let stickyTitle = $state(false);
  let sectionNav: HTMLElement;
  let indicator = $state({ left: 0, width: 0 });
  onMount(() => {
    let frame = 0;
    let stopped = false;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    function update() {
      frame = 0;
      stickyTitle = (heading?.getBoundingClientRect().bottom ?? 1) <= 0;
      const sections = links
        .map((link) => document.getElementById(link.id))
        .filter((el): el is HTMLElement => !!el);
      const threshold = navigationHeight + 64;
      let next = sections[0]?.id || "overview";
      for (const section of sections)
        if (section.getBoundingClientRect().top <= threshold) next = section.id;
      if (
        window.scrollY > 0 &&
        window.scrollY + window.innerHeight >=
          document.documentElement.scrollHeight - 2
      )
        next = sections.at(-1)?.id || next;
      const changed = next !== active;
      active = next;
      const link = sectionNav.querySelector<HTMLAnchorElement>(
        `a[href="#${next}"]`,
      );
      if (!link) return;
      indicator = { left: link.offsetLeft, width: link.offsetWidth };
      // Scroll only the horizontal navigation, never the document.
      if (
        changed &&
        (link.offsetLeft < sectionNav.scrollLeft ||
          link.offsetLeft + link.offsetWidth >
            sectionNav.scrollLeft + sectionNav.clientWidth)
      ) {
        sectionNav.scrollTo({
          left:
            link.offsetLeft - (sectionNav.clientWidth - link.offsetWidth) / 2,
          behavior: motion.matches ? "instant" : "smooth",
        });
      }
    }
    function schedule() {
      if (!frame && !stopped) frame = requestAnimationFrame(update);
    }
    window.addEventListener("scroll", schedule, { passive: true });
    const resize = new ResizeObserver(schedule);
    resize.observe(sectionNav);
    resize.observe(container);
    resize.observe(sectionNav.firstElementChild!);
    if (content) resize.observe(content);
    document.fonts.ready.then(schedule);
    schedule();
    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      resize.disconnect();
      window.removeEventListener("scroll", schedule);
    };
  });
  const links = $derived([
    { id: "overview", label: "overview", icon: BookOpen },
    { id: "requirements", label: "prerequisites", icon: GitBranch },
    { id: "professors", label: "professors", icon: Users },
    { id: "schedule", label: "calendar", icon: CalendarDays },
    { id: "experience", label: "student experience", icon: BookOpen },
    { id: "grades", label: "grades", icon: ChartColumn },
    { id: "evidence", label: "sources", icon: Layers },
  ]);
</script>

<div
  class="sticky top-0 z-20 bg-canvas border-b border-b-border course-navigation"
  bind:offsetHeight={navigationHeight}
  bind:this={container}
>
  {#if stickyTitle}<div
      class="flex items-baseline gap-3 min-w-0 pt-2.5 pb-1 sticky-course-title px-2"
      aria-hidden="true"
    >
      <span
        class="shrink-0 max-w-[45%] overflow-hidden text-ellipsis whitespace-nowrap text-muted text-[12px] sticky-course-code"
        title={code}>{code}</span
      ><span
        class="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-[15px] font-medium sticky-course-name"
        {title}>{title}</span
      >
    </div>{/if}
  <div class="flex items-center gap-5 navigation-row py-1.5 px-0">
    <nav
      bind:this={sectionNav}
      class="flex gap-[5px] overflow-x-auto static min-w-0 border-0 m-0 p-0 course-jumps"
      class:has-indicator={indicator.width > 0}
      aria-label="Course sections"
    >
      <div class="relative flex w-[max-content] gap-[5px] section-links">
        {#each links as link}<a
            class="flex items-center whitespace-nowrap text-muted h-7.5 box-border gap-[5px] py-0 px-2"
            href={"#" + link.id}
            aria-current={active === link.id ? "location" : undefined}
            ><link.icon size={14} strokeWidth={1.5} />{link.label}</a
          >{/each}
        <span
          class="absolute left-0 bottom-0 h-0.5 bg-accent rounded-[2px] pointer-events-none section-indicator"
          aria-hidden="true"
          style:width={`${indicator.width}px`}
          style:transform={`translateX(${indicator.left}px)`}
        ></span>
      </div>
    </nav>
    <div class="flex gap-2.5 shrink-0 navigation-filters">
      {@render children()}
    </div>
  </div>
</div>

<style>
  .course-jumps a {
    font: 14px var(--font-sans);
  }
  .course-jumps a:hover {
    background: var(--surface);
    color: var(--text);
  }
  .course-jumps a[aria-current="location"] {
    color: var(--accent);
  }

  .course-navigation .course-jumps {
    flex: 1;
  }
  .course-navigation .course-jumps a {
    font-size: 12px;
  }

  .section-links {
    flex: 0 0 auto;
  }
  .section-indicator {
    transition:
      transform var(--motion-travel) var(--motion-ease),
      width var(--motion-travel) var(--motion-ease);
  }
  .has-indicator a[aria-current="location"] {
    box-shadow: none;
  }
  @media (prefers-reduced-motion: reduce) {
    .section-indicator {
      transition: none;
    }
  }

  @media (max-width: 1000px) {
    .navigation-row {
      flex-wrap: wrap;
      gap: 10px;
    }
    .course-navigation .course-jumps {
      flex-basis: 100%;
    }
    .navigation-filters {
      width: 100%;
    }
  }
</style>
