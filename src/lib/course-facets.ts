/** Client-safe description of every course-search facet. SQL lives in course-query.ts. */

export const TOKEN_LIMIT = 12;

export const weekdays = [
  "mon",
  "tue",
  "wed",
  "thu",
  "fri",
  "sat",
  "sun",
] as const;
export const timeBuckets = ["morning", "afternoon", "evening"] as const;
export const instructionModes = ["in_person", "online", "mixed"] as const;
export const catalogSeasons = ["fall", "spring", "summer"] as const;
export const requisiteFilters = ["none", "listed"] as const;
export const dayMatches = ["within", "any"] as const;
export const levelBands = [
  0, 100, 200, 300, 400, 500, 600, 700, 800, 900,
] as const;
export const undergraduateLevels = [0, 100, 200, 300, 400, 500, 600] as const;
export const graduateLevels = [700, 800, 900] as const;

export type Weekday = (typeof weekdays)[number];
export type TimeBucket = (typeof timeBuckets)[number];
export type InstructionMode = (typeof instructionModes)[number];
export type CatalogSeason = (typeof catalogSeasons)[number];
export type RequisiteFilter = (typeof requisiteFilters)[number];
export type DayMatch = (typeof dayMatches)[number];
export type FacetControl = "tokens" | "range" | "days" | "instructor";

export type FacetParam = { name: string; description: string };

export type CourseFacet = {
  id: string;
  label: string;
  description: string;
  control: FacetControl;
  params: FacetParam[];
};

export const courseFacets = [
  {
    id: "tags",
    label: "Tags",
    description:
      "Course highlights, combined with AND. Uses the same evidence and thresholds as course-card badges.",
    control: "tokens",
    params: [
      {
        name: "tags",
        description:
          "small-lectures, large-lectures, higher-grades, lower-grades, or rated-teacher, combined with AND. Lecture enrollment and assigned instructors use the selected term. Grades use the latest released term at or before it, compared with the selected department (one subject) or school; requires 30+ letter grades and 10+ peer courses. These are evidence-based highlights, not predicted difficulty.",
      },
    ],
  },
  {
    id: "subject",
    label: "Department",
    description: "Subject codes, combined with OR. Example: COMPSCI,MATH.",
    control: "tokens",
    params: [
      {
        name: "subject",
        description:
          "Subject codes combined with OR, up to 12. Example: COMPSCI,MATH.",
      },
    ],
  },
  {
    id: "level",
    label: "Course number",
    description:
      "Hundred-level bands combined with OR. 700, 800, and 900 are graduate course numbers.",
    control: "tokens",
    params: [
      {
        name: "level",
        description:
          "Hundred-level bands combined with OR, from 0 through 900. Example: 300,700. Undergraduate is every band below 700. Graduate is 700, 800, and 900.",
      },
    ],
  },
  {
    id: "credits",
    label: "Credits",
    description:
      "Credits the course can be taken for. credits_min compares the course maximum; credits_max compares the course minimum.",
    control: "range",
    params: [
      {
        name: "credits_min",
        description:
          "The course can be taken for at least this many credits (its credit maximum is at least this value). 0 through 20.",
      },
      {
        name: "credits_max",
        description:
          "The course can be taken for at most this many credits (its credit minimum is at most this value). 0 through 20.",
      },
    ],
  },
  {
    id: "gpa",
    label: "Historical GPA",
    description:
      "Average of letter grades over the five years through the selected term. Courses with no letter grades in that window do not match.",
    control: "range",
    params: [
      {
        name: "gpa_min",
        description:
          "Historical letter-grade average is at least this value, from 0 through 4. Courses with no letter grades in the five-year window do not match.",
      },
      {
        name: "gpa_max",
        description:
          "Historical letter-grade average is at most this value, from 0 through 4. Courses with no letter grades in the five-year window do not match.",
      },
      {
        name: "gpa_max_exclusive",
        description:
          "Set to true to exclude the upper GPA bound, as when selecting a histogram bin. Defaults to false; requires gpa_max to have an effect.",
      },
    ],
  },
  {
    id: "requisites",
    label: "Requisites",
    description:
      "Whether the parsed catalog requisite lists a course or a condition. Unparsed requisites match neither value.",
    control: "tokens",
    params: [
      {
        name: "requisites",
        description:
          "none: parsed catalog text lists no course and no condition. listed: it lists at least one. Unparsed requisites match neither.",
      },
    ],
  },
  {
    id: "season",
    label: "Catalog season",
    description:
      "Seasons named by the catalog's typically-offered line, combined with OR. This is not the selected term's section list.",
    control: "tokens",
    params: [
      {
        name: "season",
        description:
          "fall, spring, or summer, combined with OR. Matches a typically-offered line that names that season, including every-other-term lines. Occasionally and Not Applicable match none.",
      },
    ],
  },
  {
    id: "designation",
    label: "Catalog designation",
    description:
      "Guide course-designation labels from the catalog snapshot, combined with OR. A label is not a degree-audit decision.",
    control: "tokens",
    params: [
      {
        name: "designation",
        description:
          "family:value tokens combined with OR, up to 12. Example: breadth:natural-science,quantitative-reasoning:b. A well-formed token that is not in the snapshot matches nothing. A malformed token is rejected.",
      },
    ],
  },
  {
    id: "instructor",
    label: "Instructor",
    description:
      "On recorded offerings, the person teaches the course in the selected term. On the full catalog, any recorded teaching term matches.",
    control: "instructor",
    params: [
      {
        name: "instructor",
        description:
          "Instructor uid. With recorded offerings, they must teach the course in the selected term. With the full catalog, any recorded teaching row matches.",
      },
    ],
  },
  {
    id: "days",
    label: "Days",
    description:
      "Class meetings in the selected term, Central time. Exams are ignored. within: every class day is selected. any: at least one class meeting falls on a selected day.",
    control: "days",
    params: [
      {
        name: "days",
        description:
          "Weekdays mon,tue,wed,thu,fri,sat,sun. Default days_match=within requires every class meeting that term to fall on a selected day. days_match=any requires one class meeting on a selected day. Exams are ignored.",
      },
      {
        name: "days_match",
        description: "within (default) or any. Ignored when days is empty.",
      },
    ],
  },
  {
    id: "time",
    label: "Time of day",
    description:
      "Class start in America/Chicago. Morning is before 12:00, afternoon is 12:00 until 17:00, evening is 17:00 or later. Buckets combine with OR.",
    control: "tokens",
    params: [
      {
        name: "time",
        description:
          "morning, afternoon, or evening, combined with OR. Uses the class start in America/Chicago. Morning is before 12:00, afternoon is 12:00 until 17:00, evening is 17:00 or later.",
      },
    ],
  },
  {
    id: "mode",
    label: "Meets",
    description:
      "Recorded section instruction mode for the selected term, combined with OR. When combined with days or time, one section must satisfy all of them.",
    control: "tokens",
    params: [
      {
        name: "mode",
        description:
          "in_person, online, or mixed, combined with OR. Classroom Instruction, Online Only, and Online (some classroom). When days or time is also set, one section must satisfy the whole schedule.",
      },
    ],
  },
] as const satisfies readonly CourseFacet[];

export type CourseFacetId = (typeof courseFacets)[number]["id"];

export function facetParam(name: string) {
  for (const facet of courseFacets) {
    const param = facet.params.find((item) => item.name === name);
    if (param) return param;
  }
  throw new Error(`Unknown course facet parameter: ${name}`);
}

export const panelFacetIds = [
  "tags",
  "level",
  "credits",
  "gpa",
  "requisites",
  "season",
  "designation",
  "instructor",
  "days",
  "time",
  "mode",
] as const satisfies readonly CourseFacetId[];

export function panelFacets() {
  return panelFacetIds.map((id) =>
    courseFacets.find((facet) => facet.id === id)!,
  );
}
