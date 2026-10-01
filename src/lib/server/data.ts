import publishedStatus from "../../../.site/import/status.json";
import { database, localDatabase, sqlValues } from "./database";
import { courses, instructors } from "./schema";
import { eq, sql as drizzleSql } from "drizzle-orm";
import { withInstructorUrls } from "./instructor-urls";
import {
  instructorRatingPrior,
  withInstructorRatings,
} from "./instructor-ratings";
import { ratingPriorWeight } from "$lib/instructor-ratings";
import { building, dev } from "$lib/server/runtime";
import { error } from "@sveltejs/kit";
import { coursePreviews } from "./discovery";
import { parseCourseFilters } from "./course-query";
import { courseSearchScope, searchExpression } from "./course-search";
import type { Status } from "$lib/types";
/** Existing FTS and aggregation queries retain bound parameters. */
export async function query<T = any>(
  platform: App.Platform | undefined,
  statement: string,
  values: unknown[] = [],
): Promise<T[]> {
  if (building || dev)
    return (await localDatabase()).prepare(statement).all(...sqlValues(values)) as T[];
  // All SQL templates are internal; values remain parameters in Drizzle/D1.
  const parts = statement.split("?");
  if (parts.length !== values.length + 1)
    throw new Error("SQL parameter count mismatch");
  const chunks = parts.flatMap((part, index) =>
    index < values.length
      ? [drizzleSql.raw(part), drizzleSql`${values[index]}`]
      : [drizzleSql.raw(part)],
  );
  return (await database(platform).all<T>(
    drizzleSql.join(chunks, drizzleSql.raw("")),
  )) as T[];
}
export async function status(platform?: App.Platform): Promise<Status> {
  return {
    ...publishedStatus,
    deployed_at: building || dev ? null : platform?.env.DEPLOYED_AT || null,
    site_commit: building || dev ? null : platform?.env.SITE_COMMIT || null,
  };
}
export async function pageData(
  kind: string,
  uid: string,
  platform?: App.Platform,
): Promise<any> {
  const table = kind === "courses" ? courses : instructors;
  const [r] = await database(platform)
    .select({ payload: table.payload })
    .from(table)
    .where(eq(table.uid, uid));
  if (!r)
    error(
      404,
      kind === "courses" ? "Course not found" : "Instructor not found",
    );
  return withInstructorRatings(JSON.parse(r.payload), kind, platform);
}
export async function assertRevision(url: URL, platform?: App.Platform) {
  const s = await status(platform);
  if (
    url.searchParams.has("revision") &&
    url.searchParams.get("revision") !== s.revision
  )
    error(409, "Dataset updated. Reload this page to continue.");
  return s;
}
export function pageNumber(url: URL) {
  const n = Number(url.searchParams.get("page") || 1);
  if (!Number.isInteger(n) || n < 1 || n > 10000) error(400, "Invalid page");
  return n;
}
export async function search(
  url: URL,
  platform?: App.Platform,
  suggestions = false,
) {
  const q = (url.searchParams.get("q") || "").trim();
  if (q.length > 200) error(400, "Query is too long");
  const kind =
    url.searchParams.get("kind") === "instructor" ? "instructor" : "course";
  const term = url.searchParams.get("term") || (await status(platform)).term;
  if (!/^1\d{2}[246]$/.test(term)) error(400, "Invalid term");
  const availability = url.searchParams.get("availability") || "offered";
  if (!["offered", "all"].includes(availability))
    error(400, "Invalid availability");
  const expression = searchExpression(q, kind);
  const page = pageNumber(url),
    values: unknown[] = [];
  let from = kind === "course" ? "courses c" : "instructors c";
  let where = "1=1";
  const courseQuery =
    kind === "course"
      ? parseCourseFilters(
          url.searchParams,
          term,
          availability as "offered" | "all",
        )
      : undefined;
  const ranking = url.searchParams.get("ranking");
  let prefix = "";
  if (courseQuery) {
    const scope = courseSearchScope(
      courseQuery,
      q,
      ranking,
      url.searchParams.get("sort") === "gpa",
      {
        ratingPrior: courseQuery.tags.includes("rated-teacher")
          ? await instructorRatingPrior(platform)
          : null,
      },
    );
    prefix = scope.prefix;
    from = scope.from;
    where = scope.where;
    values.push(...scope.values);
  } else {
    if (ranking) error(400, "Invalid course ranking");
    if (expression) {
      from +=
        " JOIN (SELECT uid,bm25(search,0,0,12,6,1) score FROM search WHERE search MATCH ? AND kind=?) m ON m.uid=c.uid";
      values.push(expression, kind);
    }
  }
  const sort = url.searchParams.get("sort");
  const prior =
    kind === "instructor" ? await instructorRatingPrior(platform) : null;
  const qualityCount = "json_extract(c.payload,'$.ratings.quality_count')";
  const adjustedQuality = `CASE WHEN ${qualityCount}>0 THEN (json_extract(c.payload,'$.ratings.quality')*${qualityCount}+${prior ?? "NULL"}*${ratingPriorWeight})/(${qualityCount}+${ratingPriorWeight}) END`;
  const order =
    kind === "instructor"
      ? `c.current DESC,${adjustedQuality} DESC,c.name`
      : ranking
        ? `h.history_gpa ${ranking === "hardest" ? "ASC" : "DESC"},h.grade_count DESC,c.code`
        : sort === "gpa"
          ? "CASE WHEN h.grade_count>=100 THEN 0 ELSE 1 END,CASE WHEN h.grade_count>=100 THEN h.history_gpa END DESC,c.code"
          : expression
            ? "min(m.score),c.code"
            : "c.code";
  const fields =
    kind === "course"
      ? "c.uid course_uid,c.code course_id,c.title,c.credits_min,c.credits_max,c.gpa"
      : `c.uid instructor_uid,c.name,c.current,${adjustedQuality} bayesian_quality,${qualityCount} quality_count,json_extract(c.payload,'$.ratings.difficulty') difficulty,json_extract(c.payload,'$.ratings.difficulty_count') difficulty_count,json_extract(c.payload,'$.ratings.source_url') source_url`;
  const [count] = suggestions
    ? [{ total: 0 }]
    : await query(
        platform,
        `${prefix}SELECT count(DISTINCT c.uid) total FROM ${from} WHERE ${where}`,
        values,
      );
  const items = await query(
    platform,
    `${prefix}SELECT ${fields} FROM ${from} WHERE ${where} GROUP BY c.uid ORDER BY ${order} LIMIT ? OFFSET ?`,
    [...values, suggestions ? 6 : 30, suggestions ? 0 : (page - 1) * 30],
  );
  return {
    items:
      kind === "course"
        ? suggestions
          ? items
          : await coursePreviews(
              items,
              term,
              platform,
              courseQuery?.instructor,
              courseQuery?.subjects.length === 1
                ? courseQuery.subjects[0]
                : "school",
              courseQuery?.tags,
            )
        : await withInstructorUrls(items, platform),
    total: count.total,
    page,
    kind,
    q,
    term,
    availability,
    instructor_name: courseQuery?.instructor
      ? ((
          await query(platform, "SELECT name FROM instructors WHERE uid=?", [
            courseQuery.instructor,
          ])
        )[0]?.name ?? null)
      : null,
    filters: Object.fromEntries(url.searchParams),
  };
}
export async function gradeRows(
  uid: string,
  url: URL,
  platform?: App.Platform,
) {
  const values: unknown[] = [uid];
  let where = "uid=?";
  const instructor = url.searchParams.get("instructor");
  if (instructor) {
    where +=
      " AND section<>'' AND EXISTS(SELECT 1 FROM json_each(grades.instructors) WHERE value=?)";
    values.push(instructor);
  } else where += " AND section=''";
  const term = url.searchParams.get("term");
  if (term) {
    where += " AND term=?";
    values.push(term);
  }
  const page = pageNumber(url);
  const [count] = await query(
    platform,
    `SELECT count(*) total FROM grades WHERE ${where}`,
    values,
  );
  const data = await query(
    platform,
    `SELECT payload FROM grades WHERE ${where} ORDER BY term DESC,section LIMIT 100 OFFSET ?`,
    [...values, (page - 1) * 100],
  );
  return {
    items: data.map((r) => JSON.parse(r.payload)),
    total: count.total,
    page,
  };
}
