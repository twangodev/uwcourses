<script lang="ts">
  import type { Claim, Citation, OfficialLearningOutcome } from "$lib/types";
  import {
    activityLabel,
    learningEvidence,
    supportedLearningClaims,
  } from "$lib/course-learning";
  import { safeUrl, termName } from "$lib/format";
  import CourseSection from "./CourseSection.svelte";
  import { courseLearningRelease } from "$lib/course-learning-release";

  let {
    outcomes = [],
    skills = [],
    activities = [],
    description = "",
    experimental = courseLearningRelease.derivedClaims,
  }: {
    outcomes?: OfficialLearningOutcome[];
    skills?: Claim[];
    activities?: Claim[];
    description?: string;
    experimental?: boolean;
  } = $props();
  const supportedSkills = $derived(
    experimental ? supportedLearningClaims(skills, outcomes, description) : [],
  );
  const supportedActivities = $derived(
    experimental
      ? supportedLearningClaims(activities, outcomes, description)
      : [],
  );

  function context(source: OfficialLearningOutcome | Citation) {
    return [
      source.catalog_year ? `Catalog ${source.catalog_year}` : "",
      source.term ? termName(String(source.term)) : "",
      source.observed_at
        ? `Recorded ${String(source.observed_at).slice(0, 10)}`
        : "",
    ]
      .filter(Boolean)
      .join(" · ");
  }
</script>

{#snippet sourceLink(source: OfficialLearningOutcome | Citation)}
  {@const href = safeUrl(source.source_url)}
  <span class="source">
    {#if href}<a {href}>{String(source.source || "Official course source")}</a>
    {:else}{String(source.source || "Official course source")}{/if}
    {#if context(source)}<span> · {context(source)}</span>{/if}
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

{#if outcomes.length || supportedSkills.length || supportedActivities.length}
  <CourseSection title="What you can learn" id="learning">
    <div class="learning-content">
      {#if outcomes.length}
        <section aria-label="Official learning outcomes">
          <h3>Official learning outcomes</h3>
          <ul class="outcomes">
            {#each outcomes as outcome}
              <li>
                <p>{outcome.text}</p>
                {@render sourceLink(outcome)}
              </li>
            {/each}
          </ul>
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
  </CourseSection>
{/if}

<style>
  .learning-content {
    display: grid;
    gap: 28px;
  }
  h3 {
    font-size: 17px;
    font-weight: 550;
    margin: 0 0 12px;
  }
  .outcomes,
  .learning-claims {
    display: grid;
    gap: 16px;
    padding-left: 20px;
    margin: 0;
  }
  .learning-claims + .learning-claims {
    margin-top: 16px;
  }
  .outcomes p {
    margin: 0 0 5px;
  }
  .source {
    color: var(--muted);
    font-size: 12px;
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
</style>
