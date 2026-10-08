import { schoolStatsSchema } from "$lib/school-stats";
import { z } from "zod";

export const registry = z.registry<{ id: string }>();
const named = <T extends z.ZodType>(id: string, schema: T) => {
  registry.add(schema, { id });
  return schema;
};
export const jsonValue = named("JsonValue", z.json());
const record = z.record(z.string(), jsonValue);
const number = z.number().nullable();
const string = z.string().nullable();
const extensible = <T extends z.ZodRawShape>(shape: T) =>
  z.object(shape).catchall(jsonValue);

export const datasetSchema = named(
  "Dataset",
  extensible({
    site_commit: z.string().nullable().optional(),
    revision: z.string(),
    projection_id: z.string(),
    repository: z.string(),
    observed_at: z.string(),
    built_at: z.string(),
    term: z.string(),
    terms: z.array(z.string()),
    courses: z.number().int(),
    current_instructors: z.number().int(),
    departments: z.array(
      z.object({ subject: z.string(), count: z.number().int() }),
    ),
    designations: z
      .array(
        z.object({ family: z.string(), value: z.string(), label: z.string() }),
      )
      .optional(),
  }),
);
export const citationSchema = named(
  "Citation",
  extensible({
    type: z.string().optional(),
    source_url: string.optional(),
    source_review_id: string.optional(),
    instructor_name: string.optional(),
    instructor_uid: string.optional(),
    review_date: string.optional(),
    term_id: string.optional(),
    course_id: string.optional(),
  }),
);
export const courseEvidenceSchema = named(
  "CourseEvidence",
  extensible({
    course_id: string.optional(),
    field: z.string(),
    quote: z.string(),
    outcome_index: z.number().int().nonnegative().optional(),
    source_url: string.optional(),
    source: string.optional(),
    observed_at: string.optional(),
    term: string.optional(),
    catalog_year: string.optional(),
  }),
);
export const claimSchema = named(
  "Claim",
  extensible({
    text: z.string(),
    citations: z.array(citationSchema).optional(),
    evidence: z.array(courseEvidenceSchema).optional(),
  }),
);
export const requirementsSchema = named(
  "Requirements",
  extensible({
    root: z.string(),
    status: z.string().optional(),
    notes: z.array(z.string()).optional(),
    nodes: z.array(
      extensible({
        id: z.string(),
        kind: z.string(),
        children: z.array(z.string()),
        condition: string.optional(),
        evidence: string.optional(),
        course: extensible({
          subjects: z.array(z.string()),
          course_number: z.number(),
          minimum_grade: string.optional(),
          timing: string.optional(),
        })
          .nullable()
          .optional(),
      }),
    ),
  }),
);
export const ratingSchema = named(
  "InstructorRating",
  extensible({
    quality: number.optional(),
    quality_count: number.optional(),
    difficulty: number.optional(),
    difficulty_count: number.optional(),
    bayesian_quality: number.optional(),
    source_url: string.optional(),
  }),
);
export const instructorSchema = named(
  "Instructor",
  extensible({
    instructor_uid: z.string(),
    name: string,
    instructor_url: z.string().optional(),
    ratings: ratingSchema.nullable().optional(),
  }),
);
export const gradeSchema = named(
  "GradeSnapshot",
  extensible({
    term_id: z.string(),
    term_name: string.optional(),
    course_uid: z.string().optional(),
    a: number,
    ab: number,
    b: number,
    bc: number,
    c: number,
    d: number,
    f: number,
    total: number.optional(),
    instructors: z.array(z.string()).optional(),
    observed_at: string.optional(),
    run_id: string.optional(),
  }),
);
export const studentSummarySchema = named(
  "StudentSummary",
  extensible({
    quick_take: z.array(claimSchema).optional(),
    difficulty_workload: z.array(claimSchema).optional(),
    student_experience: z.array(claimSchema).optional(),
    historical_context: z.array(claimSchema).optional(),
    teaching_history: z.array(claimSchema).optional(),
    current_instructors: z
      .array(
        extensible({ instructor_uid: z.string(), message: string.optional() }),
      )
      .optional(),
    term_id: string.optional(),
    term_name: string.optional(),
    offered: z.boolean().optional(),
  }),
);
export const officialLearningOutcomeSchema = named(
  "OfficialLearningOutcome",
  extensible({
    text: z.string(),
    source: z.string(),
    source_url: z.string(),
    observed_at: string.optional(),
    term: string.optional(),
    catalog_year: string.optional(),
  }),
);
export const courseSchema = named(
  "Course",
  extensible({
    course_uid: z.string(),
    course_id: z.string(),
    title: z.string(),
    course_number: z.number(),
    subjects: z.array(z.string()),
    description: string,
    source_url: string.optional(),
    requirements_text: string,
    credits_min: number,
    credits_max: number,
    semester: string,
    observed_at: string,
    llm_model: string.optional(),
    llm_model_revision: string.optional(),
    llm_summary: string.optional(),
    llm_topics: z.array(z.string()).nullable().optional(),
    llm_skills: z.array(z.string()).nullable().optional(),
    official_learning_outcomes: z
      .array(officialLearningOutcomeSchema)
      .optional(),
    skills_taught: z.array(claimSchema).optional(),
    activity_tags: z.array(claimSchema).optional(),
    llm_assumed_background: z.array(z.string()).nullable().optional(),
    llm_search_phrases: z.array(z.string()).nullable().optional(),
    student_summary: studentSummarySchema.nullable(),
    requirements: requirementsSchema.nullable(),
    instructors: z.array(instructorSchema),
    grade_instructors: z.array(instructorSchema),
    grades: z.array(gradeSchema),
    offerings: z.array(record),
    sections: z.array(record),
    evidence: z.record(z.string(), z.array(z.string())),
    revision: z.string(),
  }),
);
export const courseCardSchema = named(
  "CourseCard",
  extensible({
    course_uid: z.string().optional(),
    course_id: z.string(),
    title: z.string(),
    description: string.optional(),
    credits_min: number.optional(),
    credits_max: number.optional(),
    gpa: number.optional(),
  }),
);
export const searchSchema = named(
  "SearchResults",
  extensible({
    items: z.array(z.union([courseCardSchema, instructorSchema])),
    total: z.number().int(),
    page: z.number().int(),
    kind: z.enum(["course", "instructor"]),
    q: z.string(),
    term: z.string(),
    availability: z.string(),
    instructor_name: z.string().nullable().optional(),
    filters: z.record(z.string(), z.string()),
  }),
);
export const projectionSchema = named(
  "GradeProjection",
  extensible({
    target: z.string(),
    gpa: z.number(),
    interval: extensible({
      lower: z.number(),
      upper: z.number(),
      coverage: z.number(),
      terms: z.number(),
    }).nullable(),
    grades: z.array(z.object({ grade: z.string(), percentage: z.number() })),
    sourceTerms: z.array(z.string()),
    sourceCount: z.number(),
    sameSeason: z.boolean(),
  }),
);
export const courseDataSchema = named(
  "CourseData",
  z.object({
    course: courseSchema,
    context: record.nullable(),
    instructorTrends: z.array(record),
    following: z.array(z.object({ code: z.string(), title: z.string() })),
    projection: projectionSchema.nullable(),
  }),
);
export const instructorDataSchema = named(
  "InstructorData",
  extensible({
    instructor: instructorSchema,
    history: z.array(record),
    timeline: z.array(z.object({ term: z.string(), courses: z.number() })),
    term: z.string(),
    courses: z.array(record),
    reviews: extensible({
      items: z.array(record),
      total: z.number(),
      page: z.number(),
      matched: z.boolean(),
      courses: z.array(record),
    }),
  }),
);
export const departmentDataSchema = named(
  "DepartmentData",
  z.object({ subject: z.string(), results: searchSchema, stats: record }),
);
export const catalogDataSchema = named(
  "CatalogData",
  z.object({ subject: z.string(), catalog: z.array(courseCardSchema) }),
);
export const collectionDataSchema = named(
  "CollectionData",
  z.object({
    subject: z.string(),
    collection: z.enum(["easiest", "hardest"]),
    results: searchSchema,
  }),
);
export const searchDataSchema = named(
  "SearchData",
  z.object({ results: searchSchema, discoveryFiltered: z.boolean() }),
);
export const mapDataSchema = named(
  "MapData",
  z.object({
    subject: string,
    graph: z.object({ courses: z.array(record), edges: z.array(record) }),
  }),
);
export const homeDataSchema = named(
  "HomeData",
  z.object({
    courses: z.array(courseCardSchema),
    campus: z.object({
      timezone: z.literal("America/Chicago"),
      from: string.nullable(),
      through: string.nullable(),
      assetBase: string,
      maxConcurrentClasses: z.number().int().nonnegative(),
    }),
  }),
);
export const directoryDataSchema = named("DirectoryData", z.object({}));
export const dataSchemas = {
  Statistics: named(
    "StatisticsData",
    z.object({ schoolStats: schoolStatsSchema }),
  ),
  Course: courseDataSchema,
  Instructor: instructorDataSchema,
  Department: departmentDataSchema,
  Catalog: catalogDataSchema,
  Collection: collectionDataSchema,
  Search: searchDataSchema,
  Map: mapDataSchema,
  Home: homeDataSchema,
  Directory: directoryDataSchema,
} as const;
export type DocumentKind = keyof typeof dataSchemas;
export const documentSchemas = Object.fromEntries(
  Object.entries(dataSchemas).map(([kind, data]) => [
    kind,
    named(
      kind + "Document",
      z.object({
        schema_version: z.literal(1),
        url: z.string(),
        title: z.string(),
        dataset: datasetSchema,
        data,
      }),
    ),
  ]),
) as {
  [K in DocumentKind]: z.ZodObject<{
    schema_version: z.ZodLiteral<1>;
    url: z.ZodString;
    title: z.ZodString;
    dataset: typeof datasetSchema;
    data: (typeof dataSchemas)[K];
  }>;
};
export function documentKind(path: string): DocumentKind {
  if (path === "/") return "Home";
  if (path === "/stats") return "Statistics";
  if (path === "/search" || path === "/instructors/by-rating-count")
    return "Search";
  if (path === "/departments" || path === "/explorer") return "Directory";
  if (/\/(easiest|hardest)$/.test(path)) return "Collection";
  if (path.endsWith("/catalog")) return "Catalog";
  if (path.startsWith("/courses/")) return "Course";
  if (path.startsWith("/instructors/")) return "Instructor";
  if (path.startsWith("/departments/")) return "Department";
  return "Map";
}
export type Course = z.infer<typeof courseSchema>;
export type Instructor = z.infer<typeof instructorSchema>;
export type CourseDocument = z.infer<typeof documentSchemas.Course>;
export type InstructorDocument = z.infer<typeof documentSchemas.Instructor>;
export type SearchDocument = z.infer<typeof documentSchemas.Search>;
export type PublicDocument = {
  [K in DocumentKind]: z.infer<(typeof documentSchemas)[K]>;
}[DocumentKind];

export const weatherSchema = named(
  "Weather",
  z.object({
    available: z.boolean(),
    temperatureF: z.number().nullable(),
    description: z.string().nullable(),
    observedAt: z.string().nullable(),
    source: z.string(),
    sourceUrl: z.string(),
  }),
);

export const interactionSchemas = {
  Facets: named(
    "FacetResponse",
    z.object({
      revision: z.string(),
      distributions: z.record(
        z.string(),
        z.object({
          total: z.number().int().nonnegative(),
          matched: z.number().int().nonnegative(),
          missing: z.number().int().nonnegative(),
          bins: z.array(
            z.object({
              value: z.string(),
              label: z.string(),
              count: z.number().int().nonnegative(),
              matched: z.number().int().nonnegative(),
              disabled: z.boolean().optional(),
            }),
          ),
        }),
      ),
    }),
  ),
  Suggestions: named(
    "SuggestionsResponse",
    z.object({
      revision: z.string(),
      items: z.array(
        z.union([
          z.object({
            course_uid: z.string(),
            course_id: z.string(),
            title: z.string(),
          }),
          z.object({
            instructor_uid: z.string(),
            name: z.string(),
            instructor_url: z.string(),
            current: z.coerce.boolean(),
            bayesian_quality: z.number().nullable(),
          }),
        ]),
      ),
    }),
  ),
  Status: datasetSchema,
  Search: named(
    "SearchResponse",
    searchSchema.extend({ revision: z.string() }),
  ),
  Grades: named(
    "GradesResponse",
    z.object({
      items: z.array(gradeSchema),
      total: z.number(),
      page: z.number(),
      revision: z.string(),
    }),
  ),
  InstructorHistory: named(
    "InstructorHistoryResponse",
    z.object({
      items: z.array(
        z.object({
          term: z.string(),
          course_uid: z.string(),
          course_id: z.string(),
          title: z.string(),
        }),
      ),
      page: z.number(),
      revision: z.string(),
    }),
  ),
  InstructorReviews: named(
    "InstructorReviewsResponse",
    z.object({
      items: z.array(record),
      total: z.number(),
      page: z.number(),
      courses: z.array(
        z.object({ course_uid: z.string(), course_id: z.string() }),
      ),
      matched: z.boolean(),
      revision: z.string(),
    }),
  ),
  InstructorCourses: named(
    "InstructorCoursesResponse",
    z.object({
      courses: z.array(courseCardSchema),
      term: z.string(),
      revision: z.string(),
    }),
  ),
};

export type SuggestionsResponse = z.infer<
  typeof interactionSchemas.Suggestions
>;
