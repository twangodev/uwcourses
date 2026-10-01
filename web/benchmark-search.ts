import { DatabaseSync } from "node:sqlite";
import { createHash } from "node:crypto";
import { z } from "zod";
import { sqlValues } from "../src/lib/server/sql-parameters";
import { parseCourseFilters } from "../src/lib/server/course-query";
import { courseSearchScope } from "../src/lib/server/course-search";

// Query execution in local SQLite; excludes D1 network latency and card rendering.
const db = new DatabaseSync(".site/import/site.sqlite", { readOnly: true });
const metadata = z
  .object({ value: z.string() })
  .parse(db.prepare("SELECT value FROM metadata WHERE key='status'").get());
const status = z
  .object({
    term: z.string(),
    search_projection: z
      .object({ version: z.number(), terms: z.array(z.string()) })
      .optional(),
  })
  .passthrough()
  .parse(JSON.parse(metadata.value));
const { mean: prior } = z
  .object({ mean: z.number().nullable() })
  .parse(
    db
      .prepare(
        "SELECT AVG(json_extract(payload,'$.quality_rating')) mean FROM reviews WHERE json_extract(payload,'$.quality_rating') BETWEEN 1 AND 5",
      )
      .get(),
  );
const cases = [
  "availability=all",
  "availability=all&subject=COMPSCI&gpa_min=3.5",
  "availability=all&subject=COMPSCI&tags=small-lectures",
  "availability=all&subject=COMPSCI&tags=small-lectures,higher-grades",
  "availability=all&tags=small-lectures,higher-grades",
  "availability=all&tags=rated-teacher",
  "availability=offered&subject=COMPSCI&days=mon,wed&mode=in_person",
];
try {
  const results = cases.map((params) => {
    const input = new URLSearchParams(params);
    const scope = courseSearchScope(
      parseCourseFilters(
        input,
        status.term,
        input.get("availability") === "all" ? "all" : "offered",
      ),
      "",
      null,
      false,
      {
        ratingPrior: prior,
        projection: {
          available:
            !process.argv.includes("--legacy") &&
            status.search_projection?.version === 1,
          window:
            !process.argv.includes("--legacy") &&
            status.search_projection?.version === 1 &&
            status.search_projection.terms.includes(status.term),
        },
      },
    );
    const sql = `${scope.prefix}SELECT COUNT(DISTINCT c.uid) total FROM ${scope.from} WHERE ${scope.where}`;
    const statement = db.prepare(sql);
    const timings: number[] = [];
    let total = 0;
    for (let iteration = 0; iteration < 6; iteration++) {
      const started = performance.now();
      const row = z
        .object({ total: z.number().int() })
        .parse(statement.get(...sqlValues(scope.values)));
      const elapsed = performance.now() - started;
      total = row.total;
      if (iteration) timings.push(elapsed);
    }
    timings.sort((a, b) => a - b);
    const ids = z
      .array(z.object({ uid: z.string() }))
      .parse(
        db
          .prepare(
            `${scope.prefix}SELECT DISTINCT c.uid FROM ${scope.from} WHERE ${scope.where} ORDER BY c.uid`,
          )
          .all(...sqlValues(scope.values)),
      );
    return {
      params,
      total,
      median_ms: Number(timings[2].toFixed(3)),
      result_hash: createHash("sha256")
        .update(JSON.stringify(ids))
        .digest("hex"),
      ...(process.argv.includes("--explain")
        ? {
            plan: db
              .prepare("EXPLAIN QUERY PLAN " + sql)
              .all(...sqlValues(scope.values)),
          }
        : {}),
    };
  });
  console.log(
    JSON.stringify({ environment: "local SQLite", results }, null, 2),
  );
} finally {
  db.close();
}
