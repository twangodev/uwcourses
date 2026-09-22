import { error } from "@sveltejs/kit";
import {
  catalogSeasons,
  dayMatches,
  graduateLevels,
  instructionModes,
  requisiteFilters,
  timeBuckets,
  TOKEN_LIMIT,
  undergraduateLevels,
  weekdays,
  type CatalogSeason,
  type DayMatch,
  type InstructionMode,
  type RequisiteFilter,
  type TimeBucket,
  type Weekday,
} from "$lib/course-facets";

export { graduateLevels, undergraduateLevels };

export type Designation = { family: string; value: string };

export type CourseQuery = {
  subjects: string[];
  levels: number[];
  creditsMin?: number;
  creditsMax?: number;
  gpaMin?: number;
  gpaMax?: number;
  requisites?: RequisiteFilter;
  seasons: CatalogSeason[];
  designations: Designation[];
  instructor?: string;
  days: number[];
  daysMatch: DayMatch;
  times: TimeBucket[];
  modes: InstructionMode[];
  availability: "offered" | "all";
  term: string;
};

export type SqlTerm = { sql: string; values: unknown[]; history: boolean };

export type CompiledCourseQuery = {
  where: string;
  values: unknown[];
  history: boolean;
};

const weekdayIndex = new Map<string, number>(
  weekdays.map((day, index) => [day, index]),
);

export function parseCourseFilters(
  params: URLSearchParams,
  term: string,
  availability: "offered" | "all",
): CourseQuery {
  const days = tokenList(params, "days").map(known(weekdayIndex, "day"));
  return {
    subjects: tokenList(params, "subject").map(subjectCode),
    levels: unique(tokenList(params, "level").map(levelBand)),
    creditsMin: optionalNumber(params, "credits_min", 0, 20),
    creditsMax: optionalNumber(params, "credits_max", 0, 20),
    gpaMin: optionalNumber(params, "gpa_min", 0, 4),
    gpaMax: optionalNumber(params, "gpa_max", 0, 4),
    requisites: optionalChoice(params, "requisites", requisiteFilters),
    seasons: unique(tokenList(params, "season").map(choice(catalogSeasons, "season"))),
    designations: tokenList(params, "designation").map(designationToken),
    instructor: optionalText(params, "instructor", 200),
    days,
    daysMatch: optionalChoice(params, "days_match", dayMatches) ?? "within",
    times: unique(tokenList(params, "time").map(choice(timeBuckets, "time"))),
    modes: unique(tokenList(params, "mode").map(choice(instructionModes, "mode"))),
    availability,
    term,
  };
}

export function compileCourseQuery(query: CourseQuery): CompiledCourseQuery {
  const terms = [
    subjectTerm(query),
    levelTerm(query),
    creditTerm(query),
    gradeTerm(query),
    requisiteTerm(query),
    seasonTerm(query),
    designationTerm(query),
    instructorTerm(query),
    offeringTerm(query),
    scheduleTerm(query),
  ].filter((term): term is SqlTerm => term !== undefined);
  return {
    where: terms.map((term) => term.sql).join(""),
    values: terms.flatMap((term) => term.values),
    history: terms.some((term) => term.history),
  };
}

function subjectTerm(query: CourseQuery): SqlTerm | undefined {
  if (!query.subjects.length) return;
  return {
    sql: ` AND EXISTS(SELECT 1 FROM subjects s WHERE s.uid=c.uid AND s.subject IN (${placeholders(query.subjects.length)}))`,
    values: query.subjects,
    history: false,
  };
}

function levelTerm(query: CourseQuery): SqlTerm | undefined {
  if (!query.levels.length) return;
  const ranges = query.levels
    .map(() => "n.number BETWEEN ? AND ?")
    .join(" OR ");
  return {
    sql: ` AND EXISTS(SELECT 1 FROM course_numbers n WHERE n.uid=c.uid AND (${ranges}))`,
    values: query.levels.flatMap((band) => [band, band + 99]),
    history: false,
  };
}

function creditTerm(query: CourseQuery): SqlTerm | undefined {
  const parts: string[] = [];
  const values: unknown[] = [];
  if (query.creditsMin !== undefined) {
    parts.push("c.credits_max>=?");
    values.push(query.creditsMin);
  }
  if (query.creditsMax !== undefined) {
    parts.push("c.credits_min<=?");
    values.push(query.creditsMax);
  }
  if (!parts.length) return;
  return { sql: ` AND ${parts.join(" AND ")}`, values, history: false };
}

function gradeTerm(query: CourseQuery): SqlTerm | undefined {
  const parts: string[] = [];
  const values: unknown[] = [];
  if (query.gpaMin !== undefined) {
    parts.push("h.history_gpa>=?");
    values.push(query.gpaMin);
  }
  if (query.gpaMax !== undefined) {
    parts.push("h.history_gpa<=?");
    values.push(query.gpaMax);
  }
  if (!parts.length) return;
  return { sql: ` AND ${parts.join(" AND ")}`, values, history: true };
}

function requisiteTerm(query: CourseQuery): SqlTerm | undefined {
  if (!query.requisites) return;
  return {
    sql: " AND EXISTS(SELECT 1 FROM requisite_kinds r WHERE r.uid=c.uid AND r.kind=?)",
    values: [query.requisites],
    history: false,
  };
}

function seasonTerm(query: CourseQuery): SqlTerm | undefined {
  if (!query.seasons.length) return;
  return {
    sql: ` AND EXISTS(SELECT 1 FROM course_seasons s WHERE s.uid=c.uid AND s.season IN (${placeholders(query.seasons.length)}))`,
    values: query.seasons,
    history: false,
  };
}

function designationTerm(query: CourseQuery): SqlTerm | undefined {
  if (!query.designations.length) return;
  const pairs = query.designations
    .map(() => "(d.family=? AND d.value=?)")
    .join(" OR ");
  return {
    sql: ` AND EXISTS(SELECT 1 FROM course_designations d WHERE d.uid=c.uid AND (${pairs}))`,
    values: query.designations.flatMap((item) => [item.family, item.value]),
    history: false,
  };
}

function instructorTerm(query: CourseQuery): SqlTerm | undefined {
  if (!query.instructor) return;
  const termBound = query.availability === "offered";
  return {
    sql: ` AND EXISTS(SELECT 1 FROM teaching t WHERE t.course_uid=c.uid AND t.instructor_uid=?${termBound ? " AND t.term=?" : ""})`,
    values: termBound ? [query.instructor, query.term] : [query.instructor],
    history: false,
  };
}

function offeringTerm(query: CourseQuery): SqlTerm | undefined {
  if (query.availability !== "offered") return;
  return {
    sql: " AND EXISTS(SELECT 1 FROM offerings o WHERE o.uid=c.uid AND o.term=?)",
    values: [query.term],
    history: false,
  };
}

/** Class meetings only. days_match=within keeps a course when every class day is selected. */
function scheduleTerm(query: CourseQuery): SqlTerm | undefined {
  const hasDays = query.days.length > 0;
  const hasTime = query.times.length > 0;
  const hasMode = query.modes.length > 0;
  if (!hasDays && !hasTime && !hasMode) return;
  const from = hasMode
    ? "section_modes m JOIN class_meetings cm ON cm.uid=m.uid AND cm.term=m.term AND cm.section_type=m.section_type AND cm.section_number=m.section_number"
    : "class_meetings cm";
  const scope = hasMode
    ? `m.uid=c.uid AND m.term=? AND m.mode IN (${placeholders(query.modes.length)})`
    : "cm.uid=c.uid AND cm.term=?";
  const scopeValues = hasMode ? [query.term, ...query.modes] : [query.term];
  const meeting = (extra: string, extraValues: unknown[], negated = false) => ({
    sql: `${negated ? "NOT " : ""}EXISTS (SELECT 1 FROM ${from} WHERE ${scope}${extra ? ` AND ${extra}` : ""})`,
    values: [...scopeValues, ...extraValues],
  });
  const filters: string[] = [];
  const filterValues: unknown[] = [];
  if (hasDays && query.daysMatch === "any") {
    filters.push(`cm.weekday IN (${placeholders(query.days.length)})`);
    filterValues.push(...query.days);
  }
  if (hasTime) {
    filters.push(`(${query.times.map(timeWindow).join(" OR ")})`);
  }
  const parts = [meeting(filters.join(" AND "), filterValues)];
  if (hasDays && query.daysMatch === "within") {
    parts.push(
      meeting(
        `cm.weekday NOT IN (${placeholders(query.days.length)})`,
        query.days,
        true,
      ),
    );
  }
  return {
    sql: parts.map((part) => ` AND ${part.sql}`).join(""),
    values: parts.flatMap((part) => part.values),
    history: false,
  };
}

function timeWindow(bucket: TimeBucket) {
  if (bucket === "morning") return "cm.start_minute < 720";
  if (bucket === "afternoon")
    return "(cm.start_minute >= 720 AND cm.start_minute < 1020)";
  return "cm.start_minute >= 1020";
}

function tokenList(params: URLSearchParams, name: string) {
  const raw = params.get(name);
  if (!raw?.trim()) return [];
  const tokens = raw
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);
  if (tokens.length > TOKEN_LIMIT) error(400, `Too many ${name} values`);
  return tokens;
}

function optionalText(params: URLSearchParams, name: string, max: number) {
  const value = params.get(name)?.trim() || "";
  if (!value) return;
  if (value.length > max) error(400, `Invalid ${name}`);
  return value;
}

function optionalNumber(
  params: URLSearchParams,
  name: string,
  min: number,
  max: number,
) {
  const raw = params.get(name);
  if (!raw?.trim()) return;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < min || value > max)
    error(400, "Invalid numeric filter");
  return value;
}

function levelBand(value: string) {
  const band = Number(value);
  if (!Number.isInteger(band) || band < 0 || band > 900 || band % 100)
    error(400, "Invalid course level");
  return band;
}

function subjectCode(value: string) {
  if (!/^[A-Za-z0-9&-]+$/.test(value)) error(400, "Invalid subject");
  return value;
}

function designationToken(value: string): Designation {
  const match = /^([a-z0-9-]+):([a-z0-9-]+)$/.exec(value);
  if (!match) error(400, "Invalid designation");
  return { family: match[1], value: match[2] };
}

function choice<T extends string>(allowed: readonly T[], name: string) {
  return (value: string) => {
    if (!allowed.includes(value as T)) error(400, `Invalid ${name}`);
    return value as T;
  };
}

function known(index: Map<string, number>, name: string) {
  return (value: string) => {
    const found = index.get(value);
    if (found === undefined) error(400, `Invalid ${name}`);
    return found;
  };
}

function optionalChoice<T extends string>(
  params: URLSearchParams,
  name: string,
  allowed: readonly T[],
) {
  const raw = params.get(name)?.trim() || "";
  if (!raw) return;
  if (!allowed.includes(raw as T)) error(400, `Invalid ${name}`);
  return raw as T;
}

function unique<T>(values: T[]) {
  return [...new Set(values)];
}

function placeholders(count: number) {
  return Array(count).fill("?").join(",");
}
