<script lang="ts">
  import type { Claim } from "$lib/types";
  import CitationPopover from "./CitationPopover.svelte";
  let {
    claims = [],
    reviewFiles = [],
    coursePath = "",
  }: {
    claims: Claim[];
    reviewFiles?: string[];
    coursePath?: string;
  } = $props();

  // Review citations also identify the scope of older dataset releases.
  function reviewContext(claim: Claim) {
    const reviews = (claim.citations || []).filter((c) => c.type === "review");
    if (claim.evidence_scope !== "past_student_reviews" && !reviews.length)
      return null;
    const names = [
      ...new Set(reviews.map((c) => c.instructor_name).filter(Boolean)),
    ];
    return (
      "Past student reviews" + (names.length ? ` · ${names.join(", ")}` : "")
    );
  }
  const contexts = $derived(claims.map(reviewContext));
</script>

<div class="stack">
  {#each claims as claim, index}<div class="claim">
      {#if contexts[index] && contexts[index] !== contexts[index - 1]}
        <p class="review-context">{contexts[index]}</p>
      {/if}
      <p>
        {claim.text}{#if claim.citations?.length}<CitationPopover
            citations={claim.citations}
            {reviewFiles}
            {coursePath}
          />{/if}
      </p>
    </div>{/each}
</div>

<style>
  .review-context {
    color: var(--muted);
    font-size: 12px;
    margin: 0 0 6px;
  }
</style>
