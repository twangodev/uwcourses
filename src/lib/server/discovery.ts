import type { CourseTag } from "$lib/course-tags";
import { courseBadges } from "$lib/badges";
import { courseContexts } from "./course-context";
import { withInstructorUrls } from "./instructor-urls";
import { instructorRatingPrior } from "./instructor-ratings";
import { bayesianRating } from "$lib/instructor-ratings";
import { query } from "./data";
import { gradeSummary } from "$lib/discovery";

export async function coursePreviews(
  items: any[],
  term: string,
  platform?: App.Platform,
  instructor?: string,
  scope = "school",
  tags: readonly CourseTag[] = [],
) {
  if (!items.length) return [];
  if (items.length > 30) {
    const chunks: any[][] = [];
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
  const [courses, grades, teachers] = await Promise.all([
    query(
      platform,
      `SELECT uid,payload FROM courses WHERE uid IN (${placeholders})`,
      ids,
    ),
    query(
      platform,
      `SELECT * FROM grade_summaries WHERE uid IN (${placeholders}) AND term<=? AND CAST(term AS INTEGER)>?`,
      [...ids, term, Number(term) - 50],
    ),
    query(
      platform,
      `SELECT DISTINCT t.course_uid,i.uid,i.name,json_extract(i.payload,'$.ratings.quality') quality,json_extract(i.payload,'$.ratings.quality_count') quality_count FROM teaching t JOIN instructors i ON i.uid=t.instructor_uid WHERE t.course_uid IN (${placeholders}) AND t.term=? ORDER BY quality DESC,i.name`,
      [...ids, term],
    ),
  ]);
  const prior = teachers.length ? await instructorRatingPrior(platform) : null;
  const rankedTeachers = (await withInstructorUrls(teachers, platform)).map(row => ({ ...row, quality: bayesianRating(row.quality, row.quality_count ?? 0, prior) })).sort((a, b) => (b.quality ?? -1) - (a.quality ?? -1) || (a.name || "").localeCompare(b.name || ""));
  const payloads = new Map(
    courses.map((row) => [row.uid, JSON.parse(row.payload)]),
  );
  const instructorRows = instructor
    ? await query(
        platform,
        `SELECT uid,term,payload FROM grades WHERE uid IN (${placeholders}) AND section<>'' AND term<=? AND CAST(term AS INTEGER)>? AND EXISTS(SELECT 1 FROM json_each(grades.instructors) WHERE value=?)`,
        [...ids, term, Number(term) - 50, instructor],
      )
    : [];
  const contexts = await courseContexts([...payloads.values()], platform);
  return items.map((item) => {
    const course = payloads.get(item.course_uid);
    const claims = [
      ...(course.student_summary?.difficulty_workload || []),
      ...(course.student_summary?.quick_take || []),
    ];
    const teacherRows = instructorRows
      .filter((row) => row.uid === item.course_uid)
      .map((row) => ({ ...JSON.parse(row.payload), term: row.term }));
    const teacherTerms = new Set(teacherRows.map((row) => row.term));
    const teacherClaim = course.student_summary?.current_instructors
      ?.find((row: any) => row.instructor_uid === instructor)
      ?.summary?.find((row: any) => row.citations?.length);
    return {
      ...item,
      badges: courseBadges({ course, context: contexts.get(item.course_uid), term, scope, instructors: rankedTeachers.filter(row => row.course_uid === item.course_uid).map(row => ({ name: row.name, instructor_url: row.instructor_url, terms: [{ term }], ratings: { bayesian_quality: row.quality, quality_count: row.quality_count } })) }).sort((a, b) => Number(tags.includes(b.tag!)) - Number(tags.includes(a.tag!))),
      description: course.llm_summary?.replace(`${course.course_id} ${course.title} `, "").replace(/^./, (letter: string) => letter.toUpperCase()) || null,
      discovery: {
        term,
        offered: course.offerings.some((row: any) => row.term_id === term),
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
          : claims.find((row: any) =>
              row.citations?.some(
                (citation: any) => citation.type === "review",
              ),
            ) || null,
        reviewFiles: course.evidence?.reviews || [],
      },
    };
  });
}
