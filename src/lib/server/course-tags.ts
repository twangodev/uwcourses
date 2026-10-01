import { tagThresholds, type CourseTag } from "$lib/course-tags";
import { ratingPriorWeight } from "$lib/instructor-ratings";
import type { CourseQuery } from "./course-query";

/** Compute the same term-specific highlights as courseBadges, before pagination. */
export function courseTagScope(
  query: CourseQuery,
  tags: readonly CourseTag[],
  ratingPrior: number | null,
  allSubjects = false,
  projected = false,
) {
  const ctes: string[] = [];
  const values: unknown[] = [];
  const sources: string[] = [];
  const subjects = query.subjects;
  const unscoped = allSubjects ? ",NULL subject" : "";
  const subjectFilter = subjects.length
    ? ` WHERE EXISTS(SELECT 1 FROM subjects s WHERE s.uid=c.uid AND s.subject IN (${subjects.map(() => "?").join(",")}))`
    : "";
  ctes.push(
    `tag_candidates AS MATERIALIZED (SELECT c.uid FROM courses c${subjectFilter})`,
  );
  values.push(...subjects);

  if (
    tags.some((tag) => tag === "small-lectures" || tag === "large-lectures")
  ) {
    if (projected) {
      ctes.push(
        `tag_lecture_medians AS (SELECT l.uid,l.median FROM lecture_sizes l JOIN tag_candidates c ON c.uid=l.uid WHERE l.term=?)`,
      );
      values.push(query.term);
    } else {
      // Match badge deduplication: the last positive observation of each lecture wins.
      ctes.push(`tag_lecture_rows AS (
      SELECT c.uid,
        json_extract(j.value,'$.enrolled') enrolled,
        ROW_NUMBER() OVER (PARTITION BY c.uid,COALESCE(NULLIF(json_extract(j.value,'$.section_uid'),''),
          json_extract(j.value,'$.term_id')||':'||json_extract(j.value,'$.section_type')||':'||json_extract(j.value,'$.section_number'))
          ORDER BY CAST(j.key AS INTEGER) DESC) observation
      FROM tag_candidates tc JOIN courses c ON c.uid=tc.uid,json_each(c.payload,'$.sections') j
      WHERE json_extract(j.value,'$.term_id')=? AND json_extract(j.value,'$.section_type')='LEC'
        AND json_type(j.value,'$.enrolled') IN ('integer','real') AND json_extract(j.value,'$.enrolled')>0
    )`);
      values.push(query.term);
      ctes.push(`tag_lecture_order AS (
      SELECT uid,enrolled,ROW_NUMBER() OVER (PARTITION BY uid ORDER BY enrolled) position,
        COUNT(*) OVER (PARTITION BY uid) sections FROM tag_lecture_rows WHERE observation=1
    )`);
      ctes.push(`tag_lecture_medians AS (
      SELECT uid,AVG(enrolled) median FROM tag_lecture_order
      WHERE position IN ((sections+1)/2,(sections+2)/2) GROUP BY uid
    )`);
    }
    sources.push(`SELECT uid,CASE WHEN median<=${tagThresholds.smallLecture} THEN 'small-lectures' ELSE 'large-lectures' END tag${unscoped}
      FROM tag_lecture_medians WHERE median<=${tagThresholds.smallLecture} OR median>=${tagThresholds.largeLecture}`);
  }

  if (tags.some((tag) => tag === "higher-grades" || tag === "lower-grades")) {
    const count = "a+ab+b+bc+c+d+f";
    if (projected) {
      ctes.push(
        `tag_grade_terms AS (SELECT g.uid,g.term,g.grade_count count,g.gpa FROM tag_latest_grades l JOIN grade_metrics g ON g.uid=l.uid AND g.term=l.term)`,
      );
    } else
      ctes.push(`tag_grade_terms AS (
      SELECT uid,term,${count} count,(a*4+ab*3.5+b*3+bc*2.5+c*2+d)*1.0/(${count}) gpa
      FROM grade_summaries WHERE term<=? AND (${count})>0
    )`);
    if (!projected) values.push(query.term);
    if (allSubjects) {
      ctes.push(`tag_grade_cohorts AS (
        SELECT g.*,s.subject FROM tag_grade_terms g JOIN subjects s ON s.uid=g.uid
        UNION ALL SELECT g.*,'school' subject FROM tag_grade_terms g
      )`);
      if (projected)
        ctes.push(
          "tag_grade_benchmarks AS (SELECT term,subject,gpa FROM grade_benchmarks)",
        );
      else
        ctes.push(`tag_grade_benchmarks AS (
        SELECT term,subject,AVG(gpa) gpa FROM tag_grade_cohorts WHERE count>=${tagThresholds.letterGrades}
        GROUP BY term,subject HAVING COUNT(*)>=${tagThresholds.benchmarkCourses}
      )`);
    } else {
      const cohort =
        subjects.length === 1
          ? " AND EXISTS(SELECT 1 FROM subjects s WHERE s.uid=g.uid AND s.subject=?)"
          : "";
      if (projected) {
        ctes.push(
          "tag_grade_benchmarks AS (SELECT term,gpa FROM grade_benchmarks WHERE subject=?)",
        );
        values.push(subjects.length === 1 ? subjects[0] : "school");
      } else {
        ctes.push(`tag_grade_benchmarks AS (
        SELECT term,AVG(gpa) gpa FROM tag_grade_terms g WHERE count>=${tagThresholds.letterGrades}${cohort}
        GROUP BY term HAVING COUNT(*)>=${tagThresholds.benchmarkCourses}
      )`);
        if (subjects.length === 1) values.push(subjects[0]);
      }
    }
    ctes.push(
      projected
        ? "tag_latest_grades AS MATERIALIZED (SELECT c.uid,(SELECT MAX(g.term) FROM grade_metrics g WHERE g.uid=c.uid AND g.term<=?) term FROM tag_candidates c)"
        : `tag_latest_grades AS (SELECT uid,MAX(term) term FROM tag_grade_terms GROUP BY uid)`,
    );
    if (projected) values.push(query.term);
    sources.push(`SELECT g.uid,CASE WHEN g.gpa>b.gpa THEN 'higher-grades' ELSE 'lower-grades' END tag${allSubjects ? ",g.subject" : ""}
      FROM tag_latest_grades l JOIN ${allSubjects ? "tag_grade_cohorts" : "tag_grade_terms"} g ON g.uid=l.uid AND g.term=l.term
      JOIN tag_grade_benchmarks b ON b.term=g.term${allSubjects ? " AND b.subject=g.subject" : ""} JOIN tag_candidates c ON c.uid=g.uid
      WHERE g.count>=${tagThresholds.letterGrades} AND ABS(g.gpa-b.gpa)+${Number.EPSILON * 4}>=${tagThresholds.gradeDifference}`);
  }

  if (tags.includes("rated-teacher")) {
    const quality = "json_extract(i.payload,'$.ratings.quality')";
    const count = "json_extract(i.payload,'$.ratings.quality_count')";
    const adjusted = `(${quality}*${count}+?*${ratingPriorWeight})/(${count}+${ratingPriorWeight})`;
    if (projected) {
      ctes.push(
        `tag_rated_teachers AS (SELECT DISTINCT t.course_uid uid FROM teaching t JOIN instructor_search_ratings r ON r.uid=t.instructor_uid WHERE t.term=? AND r.quality BETWEEN 1 AND 5 AND r.quality_count>=${tagThresholds.qualityRatings} AND r.bayesian_quality BETWEEN ${tagThresholds.quality} AND 5)`,
      );
      values.push(query.term);
    } else {
      ctes.push(`tag_rated_teachers AS (
      SELECT DISTINCT t.course_uid uid FROM teaching t JOIN instructors i ON i.uid=t.instructor_uid
      WHERE t.term=? AND ${quality} BETWEEN 1 AND 5 AND ${count}>=${tagThresholds.qualityRatings}
        AND ${adjusted} BETWEEN ${tagThresholds.quality} AND 5
    )`);
      values.push(query.term, ratingPrior);
    }
    sources.push(
      `SELECT uid,'rated-teacher' tag${unscoped} FROM tag_rated_teachers`,
    );
  }

  ctes.push(`course_tags AS (${sources.join(" UNION ALL ")})`);
  return { ctes, values };
}
