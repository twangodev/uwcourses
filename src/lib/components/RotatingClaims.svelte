<script lang="ts">
  import { onMount } from "svelte";
  import { ChevronLeft, ChevronRight, Pause, Play } from "@lucide/svelte";
  import AIDisclaimer from "./AIDisclaimer.svelte";
  import Claims from "./Claims.svelte";
  import type { Claim, Citation, OfficialLearningOutcome } from "$lib/types";
  import {
    activityLabel,
    groupedLearningOutcomes,
    learningEvidence,
    supportedLearningClaims,
  } from "$lib/course-learning";
  import { safeUrl } from "$lib/format";
  import { courseLearningRelease } from "$lib/course-learning-release";

  let {
    claims = [],
    outcomes = [],
    skills = [],
    activities = [],
    description = "",
    experimental = courseLearningRelease.derivedClaims,
    reviewFiles = [],
    model,
    revision,
  }: {
    claims?: (Claim & { source?: string; href?: string })[];
    outcomes?: OfficialLearningOutcome[];
    skills?: Claim[];
    activities?: Claim[];
    description?: string;
    experimental?: boolean;
    reviewFiles?: string[];
    model?: string | null;
    revision?: string | null;
  } = $props();
  const displayedOutcomes = $derived(
    groupedLearningOutcomes(outcomes, description),
  );
  const outcomeSources = $derived([
    ...new Map(
      displayedOutcomes.flatMap((outcome) =>
        outcome.sources.flatMap((source) => {
          const href = safeUrl(source.source_url);
          return href ? [[href, sourceLabel(source)] as const] : [];
        }),
      ),
    ).entries(),
  ]);
  const supportedSkills = $derived(
    experimental ? supportedLearningClaims(skills, outcomes, description) : [],
  );
  const supportedActivities = $derived(
    experimental
      ? supportedLearningClaims(activities, outcomes, description)
      : [],
  );

  function sourceLabel(source: OfficialLearningOutcome | Citation) {
    return source.source === "catalog"
      ? "UW Guide"
      : String(source.source || "Official course source");
  }
  const hasLearning = $derived(
    Boolean(
      displayedOutcomes.length ||
      supportedSkills.length ||
      supportedActivities.length,
    ),
  );
  let enhanced = $state(false);
  let index = $state(0);
  let paused = $state(false);
  let container: HTMLDivElement;
  const items = $derived(
    claims.filter(
      (claim, i) =>
        claims.findIndex((other) => other.text === claim.text) === i,
    ),
  );
  const slideCount = $derived(items.length + Number(hasLearning));
  const activeIndex = $derived(index % Math.max(slideCount, 1));
  const current = $derived(items[activeIndex]);
  const learningSlide = $derived(hasLearning && activeIndex === items.length);
  function move(step: number) {
    index = (index + step + slideCount) % Math.max(slideCount, 1);
  }
  onMount(() => {
    enhanced = true;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    paused = motion.matches;
    const onMotion = () => {
      if (motion.matches) paused = true;
    };
    motion.addEventListener("change", onMotion);
    const timer = window.setInterval(() => {
      if (
        slideCount < 2 ||
        paused ||
        document.hidden ||
        container.matches(":hover") ||
        container.contains(document.activeElement) ||
        container.querySelector("[data-citation-trigger][aria-expanded=true]")
      )
        return;
      move(1);
    }, 8000);
    return () => {
      window.clearInterval(timer);
      motion.removeEventListener("change", onMotion);
    };
  });
</script>

{#snippet sourceLink(source: OfficialLearningOutcome | Citation)}
  {@const href = safeUrl(source.source_url)}
  <span class="source">
    {#if href}<a {href}>{sourceLabel(source)}</a>
    {:else}{sourceLabel(source)}{/if}
  </span>
{/snippet}

{#snippet derivedClaims(claims: Claim[], activity = false)}
  <ul class="learning-claims">
    {#each claims as claim}
      <li>
        <strong
          >{activity
            ? activityLabel(
                typeof claim.label === "string" ? claim.label : claim.text,
              )
            : claim.text}</strong
        >
        {#if activity && typeof claim.label === "string"}<p>
            {claim.text}
          </p>{/if}
        <details>
          <summary>Supporting course text</summary>
          {#each learningEvidence(claim, outcomes, description) as citation}
            <blockquote>{String(citation.quote)}</blockquote>
            {@render sourceLink(citation)}
          {/each}
        </details>
      </li>
    {/each}
  </ul>
{/snippet}

<div
  bind:this={container}
  role="region"
  aria-label="Student takeaways"
  aria-roledescription="carousel"
>
  <div class="flex items-center justify-between gap-4 mb-5 takeaway-heading">
    <div class="flex items-center gap-1.5 summary-title">
      <h2 class="m-0 text-[14px] font-[550] text-muted">Summary</h2>
      <AIDisclaimer
        {model}
        {revision}
        label="About this summary"
        description="Review summaries cite the original comments. Grade and class-size observations are calculated from recorded data. Learning outcomes come from official course text."
      />
    </div>
    {#if slideCount > 1}
      <div
        class="shrink-0 flex items-center gap-0.5 text-muted text-[12px] controls"
      >
        <button
          class="grid place-items-center w-7.5 h-7.5 p-0 border-0 bg-transparent text-inherit cursor-pointer rounded-[4px]"
          aria-label="Previous takeaway"
          onclick={() => {
            paused = true;
            move(-1);
          }}><ChevronLeft size={15} /></button
        >
        <span class="min-w-7 text-center">{activeIndex + 1} / {slideCount}</span
        >
        <button
          class="grid place-items-center w-7.5 h-7.5 p-0 border-0 bg-transparent text-inherit cursor-pointer rounded-[4px]"
          aria-label="Next takeaway"
          onclick={() => {
            paused = true;
            move(1);
          }}><ChevronRight size={15} /></button
        >
        <button
          class="grid place-items-center w-7.5 h-7.5 p-0 border-0 bg-transparent text-inherit cursor-pointer rounded-[4px]"
          aria-label={paused
            ? "Resume takeaway rotation"
            : "Pause takeaway rotation"}
          onclick={() => (paused = !paused)}
        >
          {#if paused}<Play size={13} />{:else}<Pause size={13} />{/if}
        </button>
      </div>
    {/if}
  </div>
  {#if current}
    {#key current.text}
      <div
        class="takeaway"
        role="group"
        aria-label={`${activeIndex + 1} of ${slideCount}`}
      >
        <Claims claims={[current]} {reviewFiles} />
        {#if current.source}<a
            class="inline-block mt-4 text-[12px] text-muted observation-source"
            href={current.href}>{current.source} ↗</a
          >{/if}
      </div>
    {/key}
  {/if}
  {#if hasLearning}
    <div
      class="takeaway learning-slide"
      hidden={enhanced && !learningSlide}
      role="group"
      aria-label={`${items.length + 1} of ${slideCount}`}
    >
      {#if displayedOutcomes.length}
        <section aria-label="Official learning outcomes">
          <h3>What you’ll be able to do</h3>
          <ul class="outcomes">
            {#each displayedOutcomes as outcome}
              <li>
                <p>{outcome.text}</p>
              </li>
            {/each}
          </ul>
          {#if outcomeSources.length}
            <p class="source outcome-sources">
              Source:
              {#each outcomeSources as [href, label], index}
                {#if index > 0}<span aria-hidden="true"> · </span>{/if}
                <a {href}
                  >{outcomeSources.length === 1
                    ? label
                    : `${label} ${index + 1}`}</a
                >
              {/each}
            </p>
          {/if}
        </section>
      {/if}
      {#if supportedSkills.length || supportedActivities.length}
        <section aria-label="Skills and activities from course text">
          <h3>Skills and activities</h3>
          <p class="muted explanation">
            AI-derived from official course text. The supporting passages
            describe these skills and activities; they do not establish
            assignments or workload.
          </p>
          {@render derivedClaims(supportedSkills)}
          {@render derivedClaims(supportedActivities, true)}
        </section>
      {/if}
    </div>
  {/if}
  {#if !slideCount}<p class="muted">No student feedback recorded yet.</p>{/if}
</div>

<style>
  .learning-slide:not([hidden]) {
    display: grid;
    gap: 24px;
  }
  .learning-slide {
    font-size: 14px;
  }
  h3 {
    font-size: 17px;
    font-weight: 550;
    margin: 0 0 12px;
  }
  .outcomes,
  .learning-claims {
    display: grid;
    gap: 8px;
    list-style: disc outside;
    padding-left: 20px;
    margin: 0;
  }
  .outcomes li,
  .learning-claims li {
    display: list-item;
    padding-left: 4px;
  }
  .outcomes li::marker,
  .learning-claims li::marker {
    color: var(--muted);
  }
  .learning-claims + .learning-claims {
    margin-top: 16px;
  }
  .outcomes p {
    margin: 0;
    max-width: 85ch;
  }
  .source {
    color: var(--muted);
    font-size: 12px;
  }
  .outcome-sources {
    margin: 16px 0 0;
  }
  .source a {
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .learning-claims strong {
    font-weight: 500;
  }
  .learning-claims details {
    margin-top: 5px;
  }
  summary {
    color: var(--muted);
    font-size: 12px;
    cursor: pointer;
  }
  blockquote {
    margin: 12px 0 6px;
    border-left: 2px solid var(--border);
    padding-left: 12px;
  }
  .explanation {
    font-size: 13px;
    margin: 0 0 16px;
  }

  button:hover {
    color: var(--text);
    background: var(--border);
  }
  button:focus-visible {
    outline: 2px solid var(--text);
    outline-offset: 2px;
  }
  @media (prefers-reduced-motion: no-preference) {
    .takeaway {
      animation: appear var(--motion-enter) var(--motion-ease);
    }
    @keyframes appear {
      from {
        opacity: 0;
        transform: translateY(2px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }
  }
</style>
