import { courseTags, courseTagValues, type CourseTag } from "$lib/course-tags";
import { instructorRatingPrior } from "./instructor-ratings";
import { error } from "@sveltejs/kit";
import {
  courseFacets,
  weekdays,
  timeBuckets,
  instructionModes,
} from "$lib/course-facets";
import {
  distributionIds,
  type DistributionId,
  type FacetDistribution,
  type FacetResponse,
} from "$lib/facet-distributions";
import {
  dayLabels,
  modeLabels,
  seasonLabels,
  timeLabels,
} from "$lib/course-filter-ui";
import { departmentLabel } from "$lib/departments";
import { termName, courseTitle } from "$lib/format";
import {
  courseFacetTerm,
  tagTerm,
  parseCourseFilters,
  type CourseQuery,
} from "./course-query";
import { searchProjection } from "./search-projection";
import { courseSearchScope } from "./course-search";
import { status } from "./data";
import { z } from "zod";
import { searchReadQueue } from "./search-reader";

const countRow = z.object({
  value: z.union([z.string(), z.number()]).nullable(),
  label: z.string().nullable().optional(),
  count: z.number().int().nonnegative(),
  matched: z.number().int().nonnegative(),
  total: z.number().int().nonnegative(),
  total_matched: z.number().int().nonnegative(),
  missing: z.number().int().nonnegative().optional(),
});
type FacetRead = ReturnType<typeof searchReadQueue>;

function stepBins(
  distribution: FacetDistribution,
  count: number,
  steps: number,
) {
  const indexed = new Map(distribution.bins.map((bin) => [bin.value, bin]));
  return Array.from({ length: count }, (_, index) => {
    const value = String(index / steps);
    return (
      indexed.get(value) ?? {
        value,
        label: value,
        count: 0,
        matched: 0,
      }
    );
  });
}

function parse(url: URL, fallback: string): CourseQuery {
  const term = url.searchParams.get("term") || fallback;
  if (!/^1\d{2}[246]$/.test(term)) error(400, "Invalid term");
  const availability = url.searchParams.get("availability") || "offered";
  if (availability !== "all" && availability !== "offered")
    error(400, "Invalid availability");
  return parseCourseFilters(url.searchParams, term, availability);
}

function without(url: URL, id: DistributionId) {
  const copy = new URL(url);
  for (const param of courseFacets.find((facet) => facet.id === id)?.params ??
    [])
    copy.searchParams.delete(param.name);
  return copy;
}

async function facetScope(
  url: URL,
  current: CourseQuery,
  id: DistributionId,
  platform?: App.Platform,
) {
  const context = parse(url, current.term);
  let own = courseFacetTerm(current, id);
  if (id === "availability" && current.instructor) {
    const instructor = courseFacetTerm(current, "instructor")!;
    own = own
      ? {
          ...own,
          sql: own.sql + instructor.sql,
          values: [...own.values, ...instructor.values],
        }
      : instructor;
  }
  const scope = courseSearchScope(
    context,
    (url.searchParams.get("q") || "").trim(),
    url.searchParams.get("ranking"),
    id === "gpa" || own?.history,
    {
      projection: searchProjection(context.term),
      tags: id === "tags" ? courseTagValues : undefined,
      ratingPrior:
        !searchProjection(context.term).available &&
        (id === "tags" || context.tags.includes("rated-teacher"))
          ? await instructorRatingPrior(platform)
          : null,
    },
  );
  const prefix = `${scope.prefix ? scope.prefix.trimEnd() + "," : "WITH"} eligible AS (SELECT DISTINCT c.uid,c.credits_min,c.credits_max FROM ${scope.from} WHERE ${scope.where}) `;
  const from = `eligible c${scope.history ? " LEFT JOIN history h ON h.uid=c.uid" : ""}`;
  const selected =
    id === "term"
      ? context.term === current.term
        ? "1"
        : "0"
      : own
        ? own.sql.replace(/^ AND /, "")
        : "1";
  const ownValues = id === "term" ? [] : (own?.values ?? []);
  const values = [...scope.values, ...ownValues];
  return { context, scope, prefix, from, selected, values };
}

/** The same compiler supplies both eligibility and the red current-result overlay. */
async function aggregateWithRead(
  read: FacetRead,
  url: URL,
  current: CourseQuery,
  id: DistributionId,
  value: string,
  joins = "",
  extra = "",
  platform?: App.Platform,
  label?: string,
): Promise<FacetDistribution> {
  const { scope, prefix, from, selected, values } = await facetScope(
    url,
    current,
    id,
    platform,
  );
  if (id === "tags") {
    const rows = await read(
      countRow,
      `${prefix}, tag_eligible AS (SELECT c.uid,${selected} matches FROM eligible c),
        tag_totals AS (SELECT COUNT(*) total,COUNT(CASE WHEN matches THEN 1 END) total_matched FROM tag_eligible)
        SELECT ct.tag value,COUNT(DISTINCT e.uid) count,
          COUNT(DISTINCT CASE WHEN e.matches THEN e.uid END) matched,t.total,t.total_matched
        FROM tag_totals t LEFT JOIN tag_eligible e ON 1 LEFT JOIN course_tags ct ON ct.uid=e.uid
        GROUP BY ct.tag`,
      values,
    );
    return {
      total: rows[0].total,
      matched: rows[0].total_matched,
      missing: 0,
      bins: rows
        .filter((row) => row.value != null)
        .map((row) => ({
          value: String(row.value),
          label: String(row.value),
          count: row.count,
          matched: row.matched,
        })),
    };
  }
  const bucketFrom = `eligible_matches c${scope.history ? " LEFT JOIN history h ON h.uid=c.uid" : ""}${joins}${extra ? ` WHERE ${extra}` : ""}`;
  const rows = await read(
    countRow,
    `${prefix}, eligible_matches AS MATERIALIZED (SELECT c.*,${selected} matches FROM ${from}),
      bucketed AS MATERIALIZED (SELECT c.uid,${value} value,${label || "NULL"} label,c.matches FROM ${bucketFrom}),
      totals AS (SELECT COUNT(*) total,COUNT(CASE WHEN matches THEN 1 END) total_matched,
        COUNT(*)-(SELECT COUNT(DISTINCT uid) FROM bucketed) missing FROM eligible_matches)
      SELECT b.value,MIN(b.label) label,COUNT(DISTINCT b.uid) count,
        COUNT(DISTINCT CASE WHEN b.matches THEN b.uid END) matched,t.total,t.total_matched,t.missing
      FROM totals t LEFT JOIN bucketed b ON 1 GROUP BY b.value ORDER BY count DESC,b.value`,
    values,
  );
  return {
    total: rows[0].total,
    matched: rows[0].total_matched,
    missing: rows[0].missing ?? 0,
    bins: rows
      .filter((row) => row.count > 0)
      .map((row) => ({
        value: String(row.value),
        label: row.label || String(row.value),
        count: row.count,
        matched: row.matched,
      })),
  };
}

/** Count schedule alternatives without expanding one database request per option. */
async function optionDistribution(
  read: FacetRead,
  url: URL,
  current: CourseQuery,
  id: "days" | "time" | "mode" | "availability",
  options: readonly string[],
  platform?: App.Platform,
): Promise<FacetDistribution> {
  const { prefix, from, selected, values } = await facetScope(
    url,
    current,
    id,
    platform,
  );
  const condition = (tokens: string) => {
    const candidate = new URL(url);
    candidate.searchParams.set(id, tokens);
    if (id === "days") candidate.searchParams.set("days_match", "any");
    const query = parse(candidate, current.term);
    const own = courseFacetTerm(query, id);
    const instructor =
      id === "availability" ? courseFacetTerm(query, "instructor") : undefined;
    return {
      sql: (own?.sql ?? "") + (instructor?.sql ?? ""),
      values: [...(own?.values ?? []), ...(instructor?.values ?? [])],
    };
  };
  const covered =
    id === "availability"
      ? { sql: "1", values: [] }
      : condition(options.join(","));
  const predicate = (sql: string) => sql.replace(/^ AND /, "") || "1";
  const coverage =
    id === "availability"
      ? { sql: "1", values: [] }
      : { ...covered, sql: predicate(covered.sql) };
  const columns: string[] = [];
  const binds = [...values, ...coverage.values];
  options.forEach((value, index) => {
    const candidate = condition(value);
    const sql = predicate(candidate.sql);
    columns.push(
      `COUNT(CASE WHEN ${sql} THEN 1 END) count_${index},COUNT(CASE WHEN (${sql}) AND matches THEN 1 END) matched_${index}`,
    );
    binds.push(...candidate.values, ...candidate.values);
  });
  const number = z.number().int().nonnegative();
  const [row] = await read(
    z
      .object({ total: number, total_matched: number, covered: number })
      .catchall(number),
    `${prefix}, eligible_matches AS MATERIALIZED (SELECT c.*,${selected} matches FROM ${from})
      SELECT COUNT(*) total,COUNT(CASE WHEN matches THEN 1 END) total_matched,
        COUNT(CASE WHEN ${coverage.sql} THEN 1 END) covered,${columns.join(",")} FROM eligible_matches c`,
    binds,
  );
  return {
    total: row.total,
    matched: row.total_matched,
    missing: row.total - row.covered,
    bins: options.map((value, index) => ({
      value,
      label:
        id === "days"
          ? dayLabels[value as keyof typeof dayLabels]
          : id === "time"
            ? timeLabels[value as keyof typeof timeLabels]
            : id === "mode"
              ? modeLabels[value as keyof typeof modeLabels]
              : value === "all"
                ? "Full catalog"
                : "Recorded offerings",
      count: row[`count_${index}`],
      matched: row[`matched_${index}`],
    })),
  };
}

/** Grade highlights change their comparison when selecting a department. */
async function departmentTagDistribution(
  read: FacetRead,
  url: URL,
  current: CourseQuery,
  platform?: App.Platform,
): Promise<FacetDistribution> {
  const context = parse(url, current.term);
  const scope = courseSearchScope(
    { ...context, tags: [] },
    (url.searchParams.get("q") || "").trim(),
    url.searchParams.get("ranking"),
    false,
    {
      projection: searchProjection(context.term),
      tags: context.tags,
      allTagSubjects: true,
      ratingPrior:
        !searchProjection(context.term).available &&
        context.tags.includes("rated-teacher")
          ? await instructorRatingPrior(platform)
          : null,
    },
  );
  const alternatives = tagTerm(context, { column: "s.subject" })!;
  const selected = tagTerm(current, {
    value: current.subjects.length === 1 ? current.subjects[0] : "school",
  })!;
  const subject = courseFacetTerm(current, "subject");
  const original = tagTerm(context, { value: "school" })!;
  const rows = await read(
    countRow,
    `${scope.prefix}, eligible AS (SELECT DISTINCT c.uid FROM ${scope.from} WHERE ${scope.where}),
      alternatives AS (SELECT c.uid,s.subject FROM eligible c JOIN subjects s ON s.uid=c.uid WHERE 1=1${alternatives.sql}),
      selected AS (SELECT c.uid FROM eligible c WHERE 1=1${selected.sql}${subject?.sql ?? ""}),
      totals AS (SELECT (SELECT COUNT(*) FROM eligible c WHERE 1=1${original.sql}) total,(SELECT COUNT(*) FROM selected) total_matched)
      SELECT s.subject value,COUNT(DISTINCT s.uid) count,COUNT(DISTINCT m.uid) matched,t.total,t.total_matched
      FROM totals t LEFT JOIN alternatives s ON 1 LEFT JOIN selected m ON m.uid=s.uid GROUP BY s.subject ORDER BY count DESC,value`,
    [
      ...scope.values,
      ...alternatives.values,
      ...selected.values,
      ...(subject?.values ?? []),
      ...original.values,
    ],
  );
  return {
    total: rows[0].total,
    matched: rows[0].total_matched,
    missing: 0,
    bins: rows
      .filter((row) => row.value != null)
      .map((row) => ({
        value: String(row.value),
        label: departmentLabel(String(row.value)),
        count: row.count,
        matched: row.matched,
      })),
  };
}

export async function courseDistributions(
  url: URL,
  platform?: App.Platform,
): Promise<FacetResponse> {
  const published = await status(platform);
  const current = parse(url, published.term);
  const requested = [
    ...new Set(
      (url.searchParams.get("facets") || "level,credits,gpa").split(","),
    ),
  ];
  if (requested.some((id) => !distributionIds.includes(id as DistributionId)))
    error(400, "Unknown course facet");
  const read = searchReadQueue(platform);
  const aggregate = aggregateWithRead.bind(null, read);
  const distributions = await Promise.all(
    requested.map(async (name) => {
      const id = name as DistributionId;
      const context = without(url, id);
      if (id === "availability")
        context.searchParams.set("availability", "all");
      let result: FacetDistribution;
      switch (id) {
        case "tags":
          result = await aggregate(
            context,
            current,
            id,
            "ct.tag",
            " JOIN course_tags ct ON ct.uid=c.uid",
            "",
            platform,
          );
          result.bins.forEach(
            (bin) => (bin.label = courseTags[bin.value as CourseTag].label),
          );
          break;
        case "subject":
          result = current.tags.some(
            (tag) => tag === "higher-grades" || tag === "lower-grades",
          )
            ? await departmentTagDistribution(read, context, current, platform)
            : await aggregate(
                context,
                current,
                id,
                "s.subject",
                " JOIN subjects s ON s.uid=c.uid",
                "",
                platform,
              );
          result.bins.forEach(
            (bin) => (bin.label = departmentLabel(bin.value)),
          );
          break;
        case "level":
          result = await aggregate(
            context,
            current,
            id,
            "CAST(n.number/100 AS INTEGER)*100",
            " JOIN course_numbers n ON n.uid=c.uid",
            "",
            platform,
          );
          result.bins.forEach(
            (bin) => (bin.label = `${bin.value}–${Number(bin.value) + 99}`),
          );
          result.bins.sort((a, b) => Number(a.value) - Number(b.value));
          break;
        case "credits": {
          const amounts = Array.from({ length: 41 }, (_, i) => i / 2);
          result = await aggregate(
            context,
            current,
            id,
            "v.value",
            ` JOIN json_each('${JSON.stringify(amounts)}') v ON v.value BETWEEN c.credits_min AND c.credits_max`,
            "",
            platform,
          );
          result.bins = stepBins(result, 41, 2);
          result.bins.forEach((bin) => (bin.label = `${bin.value} credits`));
          break;
        }
        case "gpa":
          result = await aggregate(
            context,
            current,
            id,
            "MIN(39,CAST(h.history_gpa*10 AS INTEGER))",
            "",
            "h.history_gpa IS NOT NULL",
            platform,
          );
          result.bins.forEach(
            (bin) => (bin.value = String(Number(bin.value) / 10)),
          );
          result.bins = stepBins(result, 40, 10);
          result.bins.forEach(
            (bin) =>
              (bin.label = `${Number(bin.value).toFixed(1)}–${Number(bin.value) === 3.9 ? "4.0" : "<" + (Number(bin.value) + 0.1).toFixed(1)}`),
          );
          break;
        case "requisites":
          result = await aggregate(
            context,
            current,
            id,
            "r.kind",
            " JOIN requisite_kinds r ON r.uid=c.uid",
            "",
            platform,
          );
          result.bins.forEach((bin) => {
            bin.label =
              bin.value === "none"
                ? "No requisites listed"
                : bin.value === "listed"
                  ? "Requisites listed"
                  : "Unparsed requisites";
            bin.disabled = bin.value === "unknown";
          });
          break;
        case "season":
          result = await aggregate(
            context,
            current,
            id,
            "s.season",
            " JOIN course_seasons s ON s.uid=c.uid",
            "",
            platform,
          );
          result.bins.forEach(
            (bin) =>
              (bin.label =
                seasonLabels[bin.value as keyof typeof seasonLabels]),
          );
          break;
        case "designation":
          result = await aggregate(
            context,
            current,
            id,
            "d.family||':'||d.value",
            " JOIN course_designations d ON d.uid=c.uid",
            "",
            platform,
            "d.label",
          );
          break;
        case "instructor":
          result = await aggregate(
            context,
            current,
            id,
            "t.instructor_uid",
            " JOIN teaching t ON t.course_uid=c.uid JOIN instructors i ON i.uid=t.instructor_uid",
            current.availability === "offered"
              ? `t.term='${current.term}'`
              : "",
            platform,
            "i.name",
          );
          result.bins.forEach((bin) => (bin.label = courseTitle(bin.label)));
          result.bins = result.bins.filter(
            (bin, i) => i < 12 || bin.value === current.instructor,
          );
          break;
        case "days":
        case "time":
        case "mode":
        case "availability":
          result = await optionDistribution(
            read,
            context,
            current,
            id,
            id === "days"
              ? weekdays
              : id === "time"
                ? timeBuckets
                : id === "mode"
                  ? instructionModes
                  : ["offered", "all"],
            platform,
          );
          break;
        case "term": {
          const options = published.terms;
          const pieces = await Promise.all(
            options.map(async (value) => {
              const candidate = new URL(context);
              candidate.searchParams.set(id, value);
              const counted = await aggregate(
                candidate,
                current,
                id,
                `'${value}'`,
                "",
                "",
                platform,
              );
              return {
                value,
                label: termName(value),
                count: counted.total,
                matched: counted.matched,
              };
            }),
          );
          const base = await aggregate(
            context,
            current,
            id,
            "'total'",
            "",
            "",
            platform,
          );
          result = { ...base, bins: pieces, missing: 0 };
          break;
        }
      }
      return [id, result] as const;
    }),
  );
  return {
    revision: published.revision,
    distributions: Object.fromEntries(distributions),
  };
}
