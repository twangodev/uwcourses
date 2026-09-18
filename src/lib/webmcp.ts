import type {} from "webmcp-types";
import { z } from "zod";
import { courseUrl } from "$lib/format";
import { representationUrl } from "$lib/documents";

const page = z.number().int().min(1).max(10000).optional();
const term = z
  .string()
  .regex(/^1\d{2}[246]$/)
  .optional()
  .describe(
    "UW term ID, e.g. 1272 for Fall 2026. Omit to use the endpoint default.",
  );
const uid = z
  .string()
  .min(1)
  .max(200)
  .regex(/^[a-zA-Z0-9_-]+$/);
const subject = z
  .string()
  .min(1)
  .max(32)
  .regex(/^[A-Za-z0-9]+$/)
  .describe("Subject code, e.g. COMPSCI.");
const instructorRef = z
  .string()
  .min(1)
  .max(200)
  .regex(/^(?:\/instructors\/)?[a-zA-Z0-9_-]+$/)
  .describe(
    "Instructor URL slug from search_instructors, e.g. HOBBES_LEGAULT or /instructors/HOBBES_LEGAULT.",
  );

type Navigate = (href: string) => Promise<void> | void;

function query(
  path: string,
  values: Record<string, string | number | undefined>,
) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) params.set(key, String(value));
  }
  return path + (params.size ? `?${params}` : "");
}

function clip(value: unknown, max = 280) {
  if (typeof value !== "string") return value ?? null;
  return value.length <= max ? value : value.slice(0, max - 1) + "…";
}

function coursePath(course: string) {
  return course.includes(" ")
    ? courseUrl(course)
    : `/courses/${encodeURIComponent(course)}`;
}

function instructorPath(instructor: string) {
  return (
    "/instructors/" +
    encodeURIComponent(instructor.replace(/^\/instructors\//, ""))
  );
}

function subjectPath(code: string, suffix = "") {
  return `/departments/${encodeURIComponent(code.toUpperCase())}${suffix}`;
}

function compactCourse(body: Record<string, any>, path: string) {
  const course = body.data?.course ?? {};
  return {
    url: body.url,
    document: path,
    course_id: course.course_id,
    course_uid: course.course_uid,
    title: course.title,
    description: clip(course.description, 400),
    requirements_text: clip(course.requirements_text),
    credits_min: course.credits_min,
    credits_max: course.credits_max,
    semester: course.semester,
    topics: Array.isArray(course.llm_topics)
      ? course.llm_topics.slice(0, 8)
      : undefined,
    instructors: (course.instructors ?? []).slice(0, 8).map((row: any) => ({
      name: row.name,
      instructor_uid: row.instructor_uid,
      instructor_url: row.instructor_url,
    })),
    following: (body.data?.following ?? []).slice(0, 8),
  };
}

function compactInstructor(body: Record<string, any>, path: string) {
  const instructor = body.data?.instructor ?? {};
  const ratings = instructor.ratings;
  return {
    url: body.url,
    document: path,
    instructor_uid: instructor.instructor_uid,
    name: instructor.name,
    instructor_url: instructor.instructor_url,
    ratings: ratings
      ? {
          quality: ratings.quality,
          quality_count: ratings.quality_count,
          bayesian_quality: ratings.bayesian_quality,
        }
      : null,
    current_courses: (body.data?.courses ?? []).slice(0, 8).map((row: any) => ({
      course_id: row.course_id,
      title: row.title,
    })),
    review_total: body.data?.reviews?.total ?? 0,
  };
}

function compactDepartment(body: Record<string, any>, path: string) {
  const data = body.data ?? {};
  return {
    url: body.url,
    document: path,
    subject: data.subject,
    total: data.results?.total,
    courses: (data.results?.items ?? []).slice(0, 12).map((row: any) => ({
      course_id: row.course_id,
      title: row.title,
      gpa: row.gpa,
    })),
    catalog: representationUrl(
      subjectPath(String(data.subject || ""), "/catalog"),
      "json",
    ),
  };
}

function compactCatalog(body: Record<string, any>, path: string) {
  const catalog = body.data?.catalog ?? [];
  return {
    url: body.url,
    document: path,
    subject: body.data?.subject,
    total: catalog.length,
    courses: catalog.slice(0, 80).map((row: any) => ({
      course_id: row.course_id,
      title: row.title,
      credits_min: row.credits_min,
      credits_max: row.credits_max,
    })),
  };
}

function compactDepartments(body: Record<string, any>) {
  return {
    term: body.term,
    observed_at: body.observed_at,
    departments: body.departments,
    document: "/departments",
  };
}

function readTool<T extends z.ZodRawShape>(
  name: string,
  description: string,
  schema: z.ZodObject<T>,
  path: (input: z.output<z.ZodObject<T>>) => string,
  compact?: (body: Record<string, any>, path: string) => unknown,
): WebMCP.ModelContextTool {
  return {
    name,
    title: name.replaceAll("_", " "),
    description,
    inputSchema: z.toJSONSchema(schema),
    annotations: { readOnlyHint: true, untrustedContentHint: true },
    async execute(input, { signal }) {
      const parsed = schema.safeParse(input);
      if (!parsed.success)
        throw new Error(`Invalid tool input: ${parsed.error.message}`);
      const href = path(parsed.data);
      const response = await fetch(href, {
        signal,
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(
          `CourseMap request failed (${response.status}). ${
            response.status === 404
              ? "Check the identifier using search_courses, search_instructors, or list_departments."
              : response.status === 409
                ? "The dataset changed; search again for current identifiers."
                : "Try again or adjust the search parameters."
          }`,
        );
      }
      if (!response.headers.get("content-type")?.includes("application/json")) {
        throw new Error(
          "Expected course data. Use search_courses to resolve an ambiguous course code.",
        );
      }
      const body = (await response.json()) as Record<string, any>;
      return JSON.stringify(compact ? compact(body, href) : body);
    },
  };
}

function navigateTool<T extends z.ZodRawShape>(
  name: string,
  description: string,
  schema: z.ZodObject<T>,
  path: (input: z.output<z.ZodObject<T>>) => string,
  navigate: Navigate,
): WebMCP.ModelContextTool {
  return {
    name,
    title: name.replaceAll("_", " "),
    description,
    inputSchema: z.toJSONSchema(schema),
    annotations: {
      readOnlyHint: false,
      untrustedContentHint: false,
      consequentialHint: false,
    },
    async execute(input) {
      const parsed = schema.safeParse(input);
      if (!parsed.success)
        throw new Error(`Invalid tool input: ${parsed.error.message}`);
      const href = path(parsed.data);
      await navigate(href);
      return `Opened ${href}`;
    },
  };
}

async function defaultNavigate(href: string) {
  const { goto } = await import("$app/navigation");
  await goto(href);
}

export function createWebmcpTools({
  navigate = defaultNavigate,
}: { navigate?: Navigate } = {}): WebMCP.ModelContextTool[] {
  return [
    readTool(
      "search_courses",
      "Search UW–Madison courses. Returns up to 30 results per page, course_uid identifiers for grade history, and course_id codes for course details. Defaults to courses offered in the dataset's current term; use availability=all to include other courses.",
      z.strictObject({
        q: z
          .string()
          .max(200)
          .optional()
          .describe("Course code or search text, e.g. CS 300 or programming."),
        subject: z
          .string()
          .min(1)
          .max(100)
          .optional()
          .describe("Subject code, e.g. COMPSCI."),
        term,
        availability: z.enum(["offered", "all"]).optional(),
        page,
        level: z.number().int().min(0).max(900).multipleOf(100).optional(),
        credits_min: z.number().min(0).max(99).optional(),
        credits_max: z.number().min(0).max(99).optional(),
        gpa_min: z.number().min(0).max(4).optional(),
        sort: z
          .enum(["gpa"])
          .optional()
          .describe(
            "Order by historical GPA; omit for default search ordering.",
          ),
        ranking: z
          .enum(["easiest", "hardest"])
          .optional()
          .describe(
            "Historical GPA ranking, requiring at least 100 grades; not a guarantee of difficulty.",
          ),
      }),
      (input) => query("/api/search", { ...input, kind: "course" }),
    ),
    readTool(
      "get_course",
      "Get a compact UW–Madison course summary: description, requirements, instructors, and the JSON document URL. Use the course_id returned by search_courses, not course_uid.",
      z.strictObject({
        course: z
          .string()
          .min(1)
          .max(100)
          .regex(/^[a-zA-Z0-9 _&/-]+$/)
          .describe("Course code, e.g. COMPSCI 300 or COMPSCI_300."),
      }),
      (input) => representationUrl(coursePath(input.course), "json"),
      compactCourse,
    ),
    readTool(
      "get_course_grades",
      "Get paginated historical grade records for a course. Use course_uid returned by search_courses. Historical grades do not predict an individual student's grade.",
      z.strictObject({
        course_uid: uid.describe(
          "Dataset course_uid from search_courses, not a course code.",
        ),
        term,
        instructor: uid.optional().describe("Optional dataset instructor UID."),
        page,
      }),
      ({ course_uid, ...filters }) =>
        query(`/api/courses/${encodeURIComponent(course_uid)}/grades`, filters),
    ),
    readTool(
      "search_instructors",
      "Search UW–Madison instructors. Returns instructor_uid for reviews, courses, and history, and instructor_url slugs for instructor documents and open_instructor.",
      z.strictObject({
        q: z
          .string()
          .max(200)
          .optional()
          .describe("Instructor name or search text."),
        page,
      }),
      (input) => query("/api/search", { ...input, kind: "instructor" }),
    ),
    readTool(
      "get_instructor",
      "Get a compact instructor summary: ratings, current courses, and review count. Use the instructor_url slug from search_instructors, not instructor_uid.",
      z.strictObject({ instructor: instructorRef }),
      (input) => representationUrl(instructorPath(input.instructor), "json"),
      compactInstructor,
    ),
    readTool(
      "get_instructor_reviews",
      "Get paginated student reviews for an instructor. Use instructor_uid from search_instructors. Reviews are student-written and may be incomplete or outdated.",
      z.strictObject({
        instructor_uid: uid.describe(
          "Dataset instructor_uid from search_instructors, not the URL slug.",
        ),
        course_uid: uid
          .optional()
          .describe("Optional dataset course_uid to limit reviews."),
        page,
      }),
      ({ instructor_uid, course_uid, page: pageNumber }) =>
        query(
          `/api/instructors/${encodeURIComponent(instructor_uid)}/reviews`,
          {
            course: course_uid,
            page: pageNumber,
          },
        ),
    ),
    readTool(
      "get_instructor_courses",
      "Get courses an instructor is teaching in a term. Use instructor_uid from search_instructors.",
      z.strictObject({
        instructor_uid: uid.describe(
          "Dataset instructor_uid from search_instructors, not the URL slug.",
        ),
        term,
      }),
      ({ instructor_uid, ...filters }) =>
        query(
          `/api/instructors/${encodeURIComponent(instructor_uid)}/courses`,
          filters,
        ),
    ),
    readTool(
      "get_instructor_history",
      "Get paginated teaching history for an instructor. Use instructor_uid from search_instructors.",
      z.strictObject({
        instructor_uid: uid.describe(
          "Dataset instructor_uid from search_instructors, not the URL slug.",
        ),
        page,
      }),
      ({ instructor_uid, page: pageNumber }) =>
        query(
          `/api/instructors/${encodeURIComponent(instructor_uid)}/history`,
          { page: pageNumber },
        ),
    ),
    readTool(
      "list_departments",
      "List UW–Madison subject codes and course counts from the current dataset.",
      z.strictObject({}),
      () => "/api/status",
      compactDepartments,
    ),
    readTool(
      "get_department",
      "Get a compact department summary and sample courses. Use a subject code from list_departments, e.g. COMPSCI.",
      z.strictObject({ subject }),
      (input) => representationUrl(subjectPath(input.subject), "json"),
      compactDepartment,
    ),
    readTool(
      "get_department_catalog",
      "Get compact catalog entries for a department. Use a subject code from list_departments. Results may be truncated; open_department for the full page.",
      z.strictObject({ subject }),
      (input) =>
        representationUrl(subjectPath(input.subject, "/catalog"), "json"),
      compactCatalog,
    ),
    navigateTool(
      "open_course",
      "Open a course page in the current tab so the student can see the full catalog UI. Use a course_id from search_courses.",
      z.strictObject({
        course: z
          .string()
          .min(1)
          .max(100)
          .regex(/^[a-zA-Z0-9 _&/-]+$/)
          .describe("Course code, e.g. COMPSCI 300 or COMPSCI_300."),
      }),
      (input) => coursePath(input.course),
      navigate,
    ),
    navigateTool(
      "open_instructor",
      "Open an instructor page in the current tab. Use the instructor_url slug from search_instructors.",
      z.strictObject({ instructor: instructorRef }),
      (input) => instructorPath(input.instructor),
      navigate,
    ),
    navigateTool(
      "open_department",
      "Open a department page in the current tab. Use a subject code from list_departments.",
      z.strictObject({ subject }),
      (input) => subjectPath(input.subject),
      navigate,
    ),
    navigateTool(
      "open_explorer",
      "Open the prerequisite explorer map. Omit subject for the directory; pass a subject code for that department's map.",
      z.strictObject({ subject: subject.optional() }),
      (input) =>
        input.subject
          ? `/explorer/${encodeURIComponent(input.subject.toUpperCase())}`
          : "/explorer",
      navigate,
    ),
    navigateTool(
      "open_search",
      "Open the search page in the current tab with optional text and entity type.",
      z.strictObject({
        q: z.string().max(200).optional().describe("Search text."),
        kind: z.enum(["course", "instructor"]).optional(),
        subject: subject.optional(),
      }),
      (input) =>
        query("/search", {
          q: input.q,
          kind: input.kind,
          subject: input.subject?.toUpperCase(),
        }),
      navigate,
    ),
  ];
}

export const courseTools = createWebmcpTools();

/** Called only after mount; unsupported browsers keep the ordinary site experience. */
export function registerCourseTools(context = document.modelContext) {
  if (!context) return () => {};
  const controller = new AbortController();
  void (async () => {
    try {
      for (const tool of courseTools) {
        if (controller.signal.aborted) return;
        await context.registerTool(tool, { signal: controller.signal });
      }
    } catch (error) {
      const disposed = controller.signal.aborted;
      controller.abort();
      if (!disposed)
        console.warn("Could not register CourseMap WebMCP tools", error);
    }
  })();
  return () => controller.abort();
}
