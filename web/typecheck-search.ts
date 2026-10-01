import {
  createSearchReadContext,
  sessionDriver,
} from "../src/lib/server/search-session";
import { courses, gradeWindows } from "../src/lib/server/schema";
import { searchCourses } from "../src/lib/server/data";
import { searchRead } from "../src/lib/server/search-reader";
import { z } from "zod";

// Compiled only: negative assertions must fail if an adapter weakens these contracts.
async function contracts(
  binding: D1Database,
  session: D1DatabaseSession,
  url: URL,
) {
  const context = createSearchReadContext(binding, "session");
  const driver: D1Database = sessionDriver(session);
  driver.prepare("SELECT 1");
  const rows = await context.orm.select({ uid: courses.uid }).from(courses);
  const uid: string = rows[0].uid;
  const gradeRows = await context.orm
    .select({ gpa: gradeWindows.historyGpa })
    .from(gradeWindows);
  const gpa: number | null = gradeRows[0].gpa;
  // @ts-expect-error unknown schema columns must remain invalid
  context.orm.select({ invalid: courses.nonexistent });
  // @ts-expect-error nullable columns cannot become unconditionally numeric
  const invalidGpa: number = gradeRows[0].gpa;
  // @ts-expect-error sessions require the explicit adapter, not a full-binding assertion
  createSearchReadContext(session);
  const decoded = await searchRead(
    undefined,
    z.object({ count: z.number() }),
    "SELECT COUNT(*) count FROM courses",
  );
  const count: number = decoded[0].count;
  // @ts-expect-error raw aggregate output follows its decoder
  const invalidCount: string = decoded[0].count;
  const results = await searchCourses(url);
  const badges = results.items[0].badges;
  return { uid, gpa, count, badges };
}
void contracts;
