import { z } from "zod";
import { claimSchema } from "$lib/api/schemas";
export const countRow = z.object({ total: z.number().int().nonnegative() });
export const courseResultRow = z.object({
  course_uid: z.string(),
  course_id: z.string(),
  title: z.string(),
  credits_min: z.number().nullable(),
  credits_max: z.number().nullable(),
  gpa: z.number().nullable(),
});
export const instructorResultRow = z.object({
  instructor_uid: z.string(),
  name: z.string().nullable(),
  current: z.number(),
  bayesian_quality: z.number().nullable(),
  quality_count: z.number().nullable(),
  difficulty: z.number().nullable(),
  difficulty_count: z.number().nullable(),
  source_url: z.string().nullable(),
});
export const gradeRow = z.object({
  uid: z.string(),
  term: z.string(),
  a: z.number(),
  ab: z.number(),
  b: z.number(),
  bc: z.number(),
  c: z.number(),
  d: z.number(),
  f: z.number(),
});
export const teacherRow = z.object({
  course_uid: z.string(),
  uid: z.string(),
  name: z.string().nullable(),
  quality: z.number().nullable(),
  quality_count: z.number().nullable(),
});
export const previewRecordRow = z.object({
  uid: z.string(),
  payload: z.string(),
  grade_term: z.string().nullable().optional(),
  latest_count: z.number().nullable().optional(),
  latest_gpa: z.number().nullable().optional(),
  benchmark_gpa: z.number().nullable().optional(),
  benchmark_size: z.number().nullable().optional(),
});
export const previewPayload = z
  .object({
    course_uid: z.string(),
    course_id: z.string(),
    semester: z.string().nullable().optional(),
    llm_summary: z.string().nullable().optional(),
    offerings: z.array(z.object({ term_id: z.string() })),
    sections: z
      .array(
        z.object({
          term_id: z.string().nullable().optional(),
          section_uid: z.string().nullable().optional(),
          section_type: z.string().nullable().optional(),
          section_number: z.string().nullable().optional(),
          enrolled: z.number().nullable().optional(),
        }),
      )
      .default([]),
    evidence: z.object({ reviews: z.array(z.string()).default([]) }),
    student_summary: z
      .object({
        difficulty_workload: z.array(claimSchema).default([]),
        quick_take: z.array(claimSchema).default([]),
        current_instructors: z
          .array(
            z.object({
              instructor_uid: z.string(),
              summary: z.array(claimSchema).default([]),
            }),
          )
          .default([]),
      })
      .nullable()
      .optional(),
  })
  .passthrough();
