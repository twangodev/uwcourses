import { z } from "zod";
import type { CourseCard } from "$lib/types";
import type { Badge } from "$lib/badges";
import { searchRead } from "./search-reader";
import { searchProjection } from "./search-projection";
import { courseResultRow, gradeRow, teacherRow, previewRecordRow, previewPayload } from "./search-rows";
import type { CourseTag } from "$lib/course-tags";
import { courseBadges } from "$lib/badges";
import { courseContexts } from "./course-context";
import { withInstructorUrls } from "./instructor-urls";
import { instructorRatingPrior } from "./instructor-ratings";
import { bayesianRating } from "$lib/instructor-ratings";
import { gradeSummary } from "$lib/discovery";

export type PreviewCard = CourseCard & { badges: Badge[] };
export async function coursePreviews(
  items: z.output<typeof courseResultRow>[],
  term: string,
  platform?: App.Platform,
  instructor?: string,
  scope = "school",
  tags: readonly CourseTag[] = [],
): Promise<PreviewCard[]> {
  if (!items.length) return [];
  if (items.length > 30) {
    const chunks: Awaited<ReturnType<typeof coursePreviews>>[] = [];
    for (let i = 0; i < items.length; i += 30)
      chunks.push(
        await coursePreviews(
          items.slice(i, i + 30),
          term,
          platform,
          instructor,
          scope,
          tags,
        ),
      );
    return chunks.flat();
  }
  const placeholders = items.map(() => "?").join(",");
  const ids = items.map((row) => row.course_uid);
  const projected = searchProjection(term).available;
  const [courses, grades, teachers] = await Promise.all([
    searchRead(platform, previewRecordRow,
      projected ? `SELECT c.uid,c.payload,g.term grade_term,g.grade_count latest_count,g.gpa latest_gpa,b.gpa benchmark_gpa,b.size benchmark_size
        FROM course_previews c LEFT JOIN grade_metrics g ON g.uid=c.uid AND g.term=(SELECT MAX(term) FROM grade_metrics WHERE uid=c.uid AND term<=?)
        LEFT JOIN grade_benchmarks b ON b.term=g.term AND b.subject=? WHERE c.uid IN (${placeholders})`
        : `SELECT uid,payload FROM courses WHERE uid IN (${placeholders})`,
      projected ? [term, scope, ...ids] : ids, "previews"),
    searchRead(
      platform, gradeRow,
      `SELECT * FROM grade_summaries WHERE uid IN (${placeholders}) AND term<=? AND CAST(term AS INTEGER)>?`,
      [...ids, term, Number(term) - 50],
    ),
    searchRead(
      platform, teacherRow,
      projected ? `SELECT DISTINCT t.course_uid,i.uid,i.name,r.bayesian_quality quality,r.quality_count FROM teaching t JOIN instructors i ON i.uid=t.instructor_uid JOIN instructor_search_ratings r ON r.uid=i.uid WHERE t.course_uid IN (${placeholders}) AND t.term=? ORDER BY quality DESC,i.name`
      : `SELECT DISTINCT t.course_uid,i.uid,i.name,json_extract(i.payload,'$.ratings.quality') quality,json_extract(i.payload,'$.ratings.quality_count') quality_count FROM teaching t JOIN instructors i ON i.uid=t.instructor_uid WHERE t.course_uid IN (${placeholders}) AND t.term=? ORDER BY quality DESC,i.name`,
      [...ids, term],
    ),
  ]);
  const prior = !projected && teachers.length ? await instructorRatingPrior(platform) : null;
  const rankedTeachers = (await withInstructorUrls(teachers, platform)).map(row => ({ ...row, quality: projected ? row.quality : bayesianRating(row.quality, row.quality_count ?? 0, prior) })).sort((a, b) => (b.quality ?? -1) - (a.quality ?? -1) || (a.name || "").localeCompare(b.name || ""));
  const payloads = new Map(
    courses.map((row) => [row.uid, previewPayload.parse(JSON.parse(row.payload))]),
  );
  const instructorRows = instructor
    ? await searchRead(
        platform, z.object({ uid: z.string(), term: z.string(), payload: z.string() }),
        `SELECT uid,term,payload FROM grades WHERE uid IN (${placeholders}) AND section<>'' AND term<=? AND CAST(term AS INTEGER)>? AND EXISTS(SELECT 1 FROM json_each(grades.instructors) WHERE value=?)`,
        [...ids, term, Number(term) - 50, instructor],
      )
    : [];
  const contexts = projected ? new Map(courses.map((row) => [row.uid, {
    terms: row.grade_term ? { [row.grade_term]: { count: row.latest_count, gpa: row.latest_gpa } } : {},
    benchmarks: { terms: row.grade_term ? { [row.grade_term]: { [scope]: row.benchmark_gpa == null ? null : { gpa: row.benchmark_gpa, size: row.benchmark_size } } } : {} },
  }])) : await courseContexts([...payloads.values()], platform);
  return items.map((item) => {
    const course = payloads.get(item.course_uid);
    if (!course) throw new Error("Missing course preview");
    const claims = [
      ...(course.student_summary?.difficulty_workload || []),
      ...(course.student_summary?.quick_take || []),
    ];
    const teacherRows = instructorRows
      .filter((row) => row.uid === item.course_uid)
      .map((row) => gradeRow.parse({ ...JSON.parse(row.payload), uid: row.uid, term: row.term }));
    const teacherTerms = new Set(teacherRows.map((row) => row.term));
    const teacherClaim = course.student_summary?.current_instructors
      ?.find((row) => row.instructor_uid === instructor)
      ?.summary?.find((row) => row.citations?.length);
    return {
      ...item,
      badges: courseBadges({ course, context: contexts.get(item.course_uid), term, scope, instructors: rankedTeachers.filter(row => row.course_uid === item.course_uid).map(row => ({ name: row.name ?? undefined, instructor_url: row.instructor_url, terms: [{ term }], ratings: { bayesian_quality: row.quality, quality_count: row.quality_count ?? 0 } })) }).sort((a, b) => Number(b.tag !== undefined && tags.includes(b.tag)) - Number(a.tag !== undefined && tags.includes(a.tag))),
      description: course.llm_summary?.replace(`${course.course_id} ${item.title} `, "").replace(/^./, (letter: string) => letter.toUpperCase()) || null,
      discovery: {
        term,
        offered: course.offerings.some((row) => row.term_id === term),
        history: gradeSummary(
          grades.filter((row) => row.uid === item.course_uid),
        ),
        instructors: rankedTeachers.filter(
          (row) => row.course_uid === item.course_uid,
        ),
        instructorHistory: instructor ? gradeSummary(teacherRows) : null,
        courseComparison: instructor
          ? gradeSummary(
              grades.filter(
                (row) =>
                  row.uid === item.course_uid && teacherTerms.has(row.term),
              ),
            )
          : null,
        claim: instructor
          ? teacherClaim || null
          : claims.find((row) =>
              row.citations?.some(
                (citation) => citation.type === "review",
              ),
            ) || null,
        reviewFiles: course.evidence?.reviews || [],
      },
    };
  });
}
