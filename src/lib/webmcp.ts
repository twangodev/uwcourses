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

function readTool<T extends z.ZodRawShape>(
  name: string,
  description: string,
  schema: z.ZodObject<T>,
  path: (input: z.output<z.ZodObject<T>>) => string,
): WebMCP.ModelContextTool {
  return {
    name,
    description,
    inputSchema: z.toJSONSchema(schema),
    annotations: { readOnlyHint: true, untrustedContentHint: true },
    async execute(input, { signal }) {
      const parsed = schema.safeParse(input);
      if (!parsed.success)
        throw new Error(`Invalid tool input: ${parsed.error.message}`);
      const response = await fetch(path(parsed.data), {
        signal,
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(
          `CourseMap request failed (${response.status}). ${
            response.status === 404
              ? "Check the course identifier using search_courses."
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
      return JSON.stringify(await response.json());
    },
  };
}

export const courseTools: WebMCP.ModelContextTool[] = [
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
        .describe("Order by historical GPA; omit for default search ordering."),
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
    "Get a UW–Madison course document including its description, requirements, and available course context. Use the course_id returned by search_courses, not course_uid.",
    z.strictObject({
      course: z
        .string()
        .min(1)
        .max(100)
        .regex(/^[a-zA-Z0-9 _&/-]+$/)
        .describe("Course code, e.g. COMPSCI 300 or COMPSCI_300."),
    }),
    ({ course }) =>
      representationUrl(
        course.includes(" ")
          ? courseUrl(course)
          : `/courses/${encodeURIComponent(course)}`,
        "json",
      ),
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
];

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
