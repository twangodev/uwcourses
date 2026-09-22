import type { gradeSummary } from "./discovery";

export type GradeSummary = ReturnType<typeof gradeSummary>;
export type DepartmentTerm = GradeSummary & {
  university: GradeSummary;
  courses: number | null;
  instructors: number;
  levels: (GradeSummary & { level: string; university: GradeSummary })[];
};
export type DepartmentStatistics = {
  all: DepartmentTerm;
  terms: Record<string, DepartmentTerm>;
};
export interface InstructorRatings {
  bayesian_quality: number | null;
  quality: number | null;
  quality_count: number;
  difficulty: number | null;
  review_count: number;
  prior_mean: number | null;
  prior_weight: number;
  source_url?: string | null;
  courses?: Record<
    string,
    { quality: number | null; difficulty: number | null; review_count: number }
  >;
}
export interface StudentReview {
  source_instructor_id: string | number;
  source_review_id: string | number;
  course_uid?: string | null;
  course_label?: string | null;
  review_date?: string | null;
  quality_rating?: number | null;
  difficulty_rating?: number | null;
  comment?: string | null;
  source_url?: string | null;
}
export interface ReviewPage {
  items: StudentReview[];
  total: number;
  page: number;
  matched: boolean;
  courses: { course_uid: string; course_id: string }[];
}

export interface CourseResults {
  items: import("./types").CourseCard[];
  total: number;
  page: number;
  term: string;
  q: string;
  availability: string;
  instructor_name?: string | null;
  filters?: Record<string, string>;
}
