import { z } from "zod";
import { courseFacets } from "$lib/course-facets";
import { registry, type DocumentKind } from "./schemas";

const query = (
  name: string,
  description: string,
  schema: Record<string, unknown> = { type: "string" },
) => ({ name, in: "query", description, schema });
const searchParameters = [
  query("q", "Search text, up to 200 characters.", {
    type: "string",
    maxLength: 200,
  }),
  query("page", "One-based page; 30 results per page.", {
    type: "integer",
    minimum: 1,
    maximum: 10000,
  }),
  query("term", "UW term ID, e.g. 1272 (Fall 2026).", {
    type: "string",
    pattern: "^1\\d{2}[246]$",
  }),
  query(
    "availability",
    "Whether courses must be offered in the selected term.",
    { type: "string", enum: ["offered", "all"] },
  ),
  ...courseFacets.flatMap((facet) =>
    facet.params.map((param) => query(param.name, param.description)),
  ),
  query("sort", "Course sort. gpa orders by historical GPA."),
  query("ranking", "Course collection ranking: easiest or hardest."),
];
const routes: [string, DocumentKind, string[]][] = [
  ["/index", "Home", []],
  ["/stats", "Statistics", ["term"]],
  ["/courses/{course}", "Course", []],
  ["/courses/easiest", "Collection", []],
  ["/courses/hardest", "Collection", []],
  ["/instructors/{instructor}", "Instructor", []],
  ["/instructors/by-rating-count", "Search", ["search"]],
  ["/departments", "Directory", []],
  ["/departments/{subject}", "Department", []],
  ["/departments/{subject}/catalog", "Catalog", []],
  ["/departments/{subject}/easiest", "Collection", []],
  ["/departments/{subject}/hardest", "Collection", []],
  ["/search", "Search", ["search"]],
  ["/explorer", "Directory", []],
  ["/explorer/all", "Map", []],
  ["/explorer/{subject}", "Map", []],
];
export function openapiSpec() {
  const paths: Record<string, unknown> = {};
  for (const [path, kind, filters] of routes)
    for (const format of ["json", "md"]) {
      const parameters = [...path.matchAll(/\{([^}]+)\}/g)].map((match) => ({
        name: match[1],
        in: "path",
        required: true,
        schema: { type: "string" },
        description:
          match[1] === "course"
            ? "Canonical course code, e.g. COMPSCI_300."
            : "Canonical URL identifier.",
      }));
      const responseSchema =
        format === "json"
          ? { $ref: `#/components/schemas/${kind}Document` }
          : { type: "string" };
      paths[path + "." + format] = {
        get: {
          operationId: (path + "_" + format)
            .replace(/[^a-zA-Z0-9]+/g, "_")
            .replace(/^_/, ""),
          summary: `${kind} as ${format === "json" ? "JSON" : "Markdown"}`,
          tags: [kind],
          parameters: [
            ...parameters,
            ...(filters.includes("search") ? searchParameters : filters.includes("term") ? searchParameters.filter(p => p.name === "term") : []),
          ],
          responses: {
            "200": {
              description: "Public document from the pinned dataset.",
              content: {
                [format === "json" ? "application/json" : "text/markdown"]: {
                  schema: responseSchema,
                },
              },
              headers: {
                ETag: {
                  schema: { type: "string" },
                  description: "Present on cacheable production GET responses.",
                },
              },
            },
            "304": { description: "Cached document matches If-None-Match." },
            "307": {
              description: "Ambiguous alias; follow Location to discovery.",
              headers: { Location: { schema: { type: "string" } } },
            },
            "308": {
              description: "Canonical identifier; follow Location.",
              headers: { Location: { schema: { type: "string" } } },
            },
            "400": { description: "Invalid query." },
            "404": { description: "Document not found." },
            "503": { description: "Dataset unavailable." },
          },
        },
      };
    }
  const interactions = [
    ["/api/status", "Status", "Dataset"],
    ["/api/search", "Search", "SearchResponse"],
    ["/api/facets", "Facets", "FacetResponse"],
    ["/api/suggest", "Suggestions", "SuggestionsResponse"],
    ["/api/courses/{uid}/grades", "Grades", "GradesResponse"],
    [
      "/api/instructors/{uid}/history",
      "InstructorHistory",
      "InstructorHistoryResponse",
    ],
    [
      "/api/instructors/{uid}/reviews",
      "InstructorReviews",
      "InstructorReviewsResponse",
    ],
    [
      "/api/instructors/{uid}/courses",
      "InstructorCourses",
      "InstructorCoursesResponse",
    ],
  ] as const;
  for (const [path, name, schema] of interactions) {
    const parameters: Record<string, unknown>[] = path.includes("{uid}")
      ? [
          {
            name: "uid",
            in: "path",
            required: true,
            description: "Dataset entity UID (not the display-name URL).",
            schema: { type: "string" },
          },
        ]
      : [];
    if (name !== "Status")
      parameters.push(
        query("revision", "Optional pinned HF revision; mismatch returns 409."),
      );
    if (name === "Facets")
      parameters.push(
        ...searchParameters.filter(
          (parameter) => !["page", "sort"].includes(parameter.name),
        ),
        query(
          "facets",
          "Comma-separated distribution names. Counts cover every result and hold other filters fixed; matched is the current-result overlay.",
        ),
      );
    else if (name === "Search" || name === "Suggestions")
      parameters.push(
        ...searchParameters.filter(
          (parameter) => name !== "Suggestions" || parameter.name !== "page",
        ),
        query("kind", "Entity type.", {
          type: "string",
          enum: ["course", "instructor"],
        }),
      );
    else if (name !== "Status") {
      if (name !== "InstructorCourses")
        parameters.push(
          query("page", "One-based result page.", {
            type: "integer",
            minimum: 1,
            maximum: 10000,
          }),
        );
      if (name === "Grades" || name === "InstructorCourses")
        parameters.push(query("term", "UW term ID."));
      if (name === "Grades")
        parameters.push(query("instructor", "Dataset instructor UID."));
      if (name === "InstructorReviews")
        parameters.push(query("course", "Dataset course UID."));
    }
    paths[path] = {
      get: {
        operationId: "api" + name,
        tags: ["Interactions"],
        summary: name,
        parameters,
        responses: {
          "200": {
            description: "Validated response.",
            content: {
              "application/json": {
                schema: { $ref: "#/components/schemas/" + schema },
              },
            },
          },
          "400": { description: "Invalid query." },
          "404": { description: "Entity not found." },
          "409": {
            description:
              "Dataset revision changed; reload with the current revision.",
          },
          "503": { description: "Dataset unavailable." },
        },
      },
    };
  }
  paths["/api/weather"] = {
    get: {
      operationId: "madisonWeather",
      summary: "Cached Madison weather observations",
      responses: {
        "200": {
          description:
            "Current observations, or available=false when unavailable or stale.",
          content: {
            "application/json": {
              schema: { $ref: "#/components/schemas/Weather" },
            },
          },
        },
      },
    },
  };
  const { schemas } = z.toJSONSchema(registry, {
    uri: (id) => "#/components/schemas/" + id,
  });
  for (const schema of Object.values(schemas)) {
    delete schema.$id;
    delete schema.$schema;
  }
  return {
    openapi: "3.1.0",
    info: {
      title: "UW Courses document API",
      version: "1.0.0",
      description:
        "Read-only course, instructor, department, discovery and prerequisite-map documents. JSON and Markdown share the website loaders. Dataset revision and model provenance are preserved. Additional imported fields are JSON values. Paged /api interaction endpoints are included; linked /data evidence files are immutable dataset assets.",
    },
    servers: [{ url: "https://uwcourses.com" }],
    paths,
    components: { schemas },
  };
}
