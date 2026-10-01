import { sqliteTable, text, real, integer } from "drizzle-orm/sqlite-core";
// Read model owned by the HF importer; migrations remain part of that import.
export const metadata = sqliteTable("metadata", {
  key: text("key").primaryKey(),
  value: text("value").notNull(),
});
export const courses = sqliteTable("courses", {
  uid: text("uid").primaryKey(),
  code: text("code"),
  title: text("title"),
  description: text("description"),
  creditsMin: real("credits_min"),
  creditsMax: real("credits_max"),
  gpa: real("gpa"),
  payload: text("payload").notNull(),
});
export const instructors = sqliteTable("instructors", {
  uid: text("uid").primaryKey(),
  name: text("name"),
  current: integer("current"),
  payload: text("payload").notNull(),
});

export const lectureSizes = sqliteTable("lecture_sizes", {
  uid: text("uid").notNull(),
  term: text("term").notNull(),
  median: real("median").notNull(),
  sections: integer("sections").notNull(),
});
export const gradeMetrics = sqliteTable("grade_metrics", {
  uid: text("uid").notNull(),
  term: text("term").notNull(),
  gradeCount: integer("grade_count").notNull(),
  gpa: real("gpa").notNull(),
});
export const gradeBenchmarks = sqliteTable("grade_benchmarks", {
  term: text("term").notNull(),
  subject: text("subject").notNull(),
  gpa: real("gpa").notNull(),
  size: integer("size").notNull(),
});
export const gradeWindows = sqliteTable("grade_windows", {
  term: text("term").notNull(),
  uid: text("uid").notNull(),
  a: integer("a").notNull(),
  ab: integer("ab").notNull(),
  b: integer("b").notNull(),
  bc: integer("bc").notNull(),
  c: integer("c").notNull(),
  d: integer("d").notNull(),
  f: integer("f").notNull(),
  gradeCount: integer("grade_count").notNull(),
  historyGpa: real("history_gpa"),
  firstTerm: text("first_term"),
  lastTerm: text("last_term"),
});
export const instructorSearchRatings = sqliteTable(
  "instructor_search_ratings",
  {
    uid: text("uid").primaryKey(),
    quality: real("quality"),
    qualityCount: integer("quality_count").notNull(),
    bayesianQuality: real("bayesian_quality"),
  },
);
export const coursePreviewRecords = sqliteTable("course_previews", {
  uid: text("uid").primaryKey(),
  payload: text("payload").notNull(),
});
