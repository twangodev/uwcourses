<script lang="ts">
  import { gradeColors as colors } from "$lib/chart-theme";
  import { courseUrl, credits, courseTitle, termName } from "$lib/format";
  import type { CourseCard } from "$lib/types";
  import Badges from "./Badges.svelte";
  import Claims from "./Claims.svelte";
  import AnimatedNumber from "./AnimatedNumber.svelte";
  let { courses, rankStart }: { courses: CourseCard[]; rankStart?: number } =
    $props();
</script>

<div class="grid gap-6 course-results">
  {#each courses as c, index}
    {#if c.discovery}{@const d = c.discovery}
      <article
        class="border-b border-b-border min-w-0 discovery-card py-6.5 px-0"
      >
        <div class="flex justify-between items-start gap-6 card-heading">
          <a
            class="min-w-0 wrap-anywhere text-foreground no-underline"
            href={courseUrl(c.course_id)}
            ><span class="text-accent text-[12px] code"
              >{#if rankStart}<span class="muted"
                  >#{rankStart + index} ·
                </span>{/if}{c.course_id}</span
            >
            <h3
              class="text-[23px] font-medium mt-[7px] mb-0 leading-[1.25] mx-0"
            >
              {courseTitle(c.title)}
            </h3></a
          ><span class="text-[12px] text-muted whitespace-nowrap credits"
            >{credits(c.credits_min, c.credits_max)}</span
          >
        </div>
        <Badges badges={c.badges || []} />
        {#if c.description}<p
            class="overflow-hidden max-w-[75ch] mt-3.5 mb-0 text-muted text-[14px] font-normal leading-[1.65] course-description mx-0"
          >
            {c.description}
          </p>{/if}
        <p class="text-[12px] text-muted mt-2.5 offering">
          {d.offered
            ? `Offering recorded · ${termName(d.term)}`
            : `No offering record · ${termName(d.term)}`}
        </p>
        {#if d.claim}<div class="max-w-[70ch] text-[14px] takeaway my-5 mx-0">
            <Claims
              claims={[d.claim]}
              reviewFiles={d.reviewFiles}
              coursePath={courseUrl(c.course_id)}
            />
          </div>{/if}
        {#if d.instructorHistory?.count}<p
            class="text-[12px] text-muted mt-5 instructor-comparison"
          >
            <strong
              ><AnimatedNumber
                value={d.instructorHistory.gpa}
                decimals={2}
              /></strong
            >
            with this instructor · <AnimatedNumber
              value={d.courseComparison?.gpa ?? null}
              decimals={2}
            /> course overall, matching historical terms
          </p>{/if}
        <div class="flex justify-between items-end gap-6 mt-5.5 card-bottom">
          <div class="flex flex-wrap gap-y-2 gap-x-4 text-[13px] teachers">
            {#each d.instructors.slice(0, 2) as i}<a href={i.instructor_url}
                >{courseTitle(i.name || "Unknown instructor")}</a
              >{/each}{#if d.instructors.length > 2}<span class="muted"
                >+{d.instructors.length - 2} more</span
              >{/if}
          </div>
          {#if d.history.count}<div
              class="shrink-0 text-[12px] min-w-52.5 history"
            >
              <div
                class="flex gap-0.5 h-[5px] rounded-[3px] overflow-hidden opacity-[0.75] grade-strip"
                role="img"
                aria-label={d.history.counts
                  .map(
                    (n, i) =>
                      `${["A", "AB", "B", "BC", "C", "D", "F"][i]} ${Math.round((n / d.history.count) * 100)}%`,
                  )
                  .join(", ")}
              >
                {#each d.history.counts as n, i}<span
                    style:width={`${(n / d.history.count) * 100}%`}
                    style:background={colors[i]}
                  ></span>{/each}
              </div>
              <p class="mt-2 mb-1 mx-0">
                <strong
                  ><AnimatedNumber value={d.history.gpa} decimals={2} /></strong
                >
                historical GPA · <AnimatedNumber value={d.history.count} /> grades
              </p>
              <small class="text-muted text-[11px]"
                >{#if d.history.firstTerm && d.history.lastTerm}{termName(d.history.firstTerm)}–{termName(
                  d.history.lastTerm,
                )}{/if}{d.history.count < 100 ? " · limited sample" : ""}</small
              >
            </div>{:else}<p class="muted">No recorded grade history</p>{/if}
        </div>
      </article>
    {:else}<a class="course-row" href={courseUrl(c.course_id)}
        ><span class="text-accent text-[12px] code">{c.course_id}</span><span
          class="course-title"
          title={c.title}
          >{courseTitle(c.title)}{#if c.description}<span
              class="overflow-hidden max-w-[75ch] mt-3.5 mb-0 text-muted text-[14px] font-normal leading-[1.65] course-description mx-0"
              >{c.description}</span
            >{/if}</span
        ><span class="muted mono"
          >{credits(c.credits_min, c.credits_max)}{c.gpa != null
            ? ` · ${c.gpa.toFixed(2)} GPA`
            : ""}</span
        ></a
      >{/if}
  {:else}<p class="empty">
      No courses match this selection. Try the full catalog or another term.
    </p>{/each}
</div>

<style>
  .course-description {
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
  }
  @media (max-width: 600px) {
    .card-bottom {
      align-items: start;
      flex-direction: column;
    }
    .history {
      width: 100%;
    }
    .card-heading {
      gap: 12px;
    }
    h3 {
      font-size: 21px;
    }
  }
</style>
