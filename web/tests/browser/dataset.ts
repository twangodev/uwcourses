import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { courseUrl } from "../../../src/lib/format";

/** Pick fixtures by the evidence needed, rather than release-specific identities. */
export function importedCourse(where: string, required = true): any {
  const db = new DatabaseSync(".site/import/site.sqlite", { readOnly: true });
  try {
    const row = db
      .prepare(
        `SELECT payload FROM courses c WHERE ${where} ORDER BY uid LIMIT 1`,
      )
      .get() as { payload: string } | undefined;
    if (!row && required)
      throw new Error(`No imported course satisfies browser fixture: ${where}`);
    return row ? JSON.parse(row.payload) : null;
  } finally {
    db.close();
  }
}
export const currentCourse = importedCourse(`
  json_array_length(payload,'$.official_learning_outcomes') > 0
  AND json_array_length(payload,'$.grade_instructors') >= 5
  AND (SELECT count(*) FROM grade_summaries g WHERE g.uid=c.uid) >= 6
  AND (SELECT count(*) FROM json_each(c.payload,'$.sections') s WHERE json_extract(s.value,'$.section_type')='LEC') >= 2
  AND EXISTS (SELECT 1 FROM json_each(c.payload,'$.instructors') r JOIN instructors i ON i.uid=json_extract(r.value,'$.instructor_uid') WHERE json_extract(i.payload,'$.ratings.quality_count') >= 10)
`);
export const currentPath = courseUrl(currentCourse.course_id);
export const importedStatus = JSON.parse(
  readFileSync(".site/import/status.json", "utf8"),
);
export const latestGradeTerm = currentCourse.grades
  .map((g: any) => g.term_id)
  .sort()
  .at(-1);
export function importedAsset(path: string): any[] {
  return JSON.parse(readFileSync(".site/import/assets" + path, "utf8"));
}
