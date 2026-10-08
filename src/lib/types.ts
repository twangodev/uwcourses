export type RecordData = Record<string, any>;
export interface OfficialLearningOutcome {
  text: string;
  source: string;
  source_url: string | null;
  observed_at?: string | null;
  term?: string | null;
  catalog_year?: string | null;
}
export interface CourseCard {
  course_uid: string;
  course_id: string;
  title: string;
  description?: string | null;
  badges?: import("./badges").Badge[];
  credits_min: number | null;
  credits_max: number | null;
  gpa: number | null;
  discovery?: {
    term: string;
    offered: boolean;
    history: ReturnType<typeof import("./discovery").gradeSummary>;
    instructors: {
      instructor_url?: string;
      uid: string;
      name: string | null;
      quality: number | null;
    }[];
    claim: Claim | null;
    reviewFiles: string[];
    instructorHistory?: ReturnType<
      typeof import("./discovery").gradeSummary
    > | null;
    courseComparison?: ReturnType<
      typeof import("./discovery").gradeSummary
    > | null;
  };
}
export interface Status {
  search_projection?: { version: number; terms: string[] };
  site_commit?: string | null;
  deployed_at?: string | null;
  revision: string;
  repository: string;
  observed_at: string;
  built_at: string;
  term: string;
  terms: string[];
  courses: number;
  current_instructors: number;
  departments: { subject: string; count: number }[];
  designations?: { family: string; value: string; label: string }[];
}
export type Citation = import("zod").infer<
  typeof import("./api/schemas").citationSchema
>;
export type Claim = import("zod").infer<
  typeof import("./api/schemas").claimSchema
>;
export interface RequirementNode {
  id: string;
  kind: string;
  children: string[];
  condition?: string;
  evidence?: string;
  course?: {
    subjects: string[];
    course_number: number;
    minimum_grade?: string;
    timing?: string;
  };
}
export interface Requirements {
  root: string;
  nodes: RequirementNode[];
  status?: string;
  notes?: string[];
}
