import { z } from "zod";
import { building, dev } from "$lib/server/runtime";
import { error } from "@sveltejs/kit";
import { localDatabase } from "./database";

export type SearchReadContext = {
  client: Pick<D1Database, "prepare" | "batch">;
  report?: (measurement: QueryMeasurement) => void;
};
export type QueryMeasurement = {
  family: string;
  wall_ms: number;
  statements: number;
  rows_returned: number;
  rows_read?: number;
  sql_ms?: number;
  region?: string;
  primary?: boolean;
};
type Statement = { sql: string; values?: readonly unknown[]; family?: string };

function parameters(statement: Statement) {
  const values = (statement.values ?? []).map((value) => {
    if (value === null || typeof value === "string" || (typeof value === "number" && Number.isFinite(value))) return value;
    throw new Error("Invalid search SQL parameter");
  });
  if (statement.sql.split("?").length !== values.length + 1)
    throw new Error("SQL parameter count mismatch");
  return values;
}

export async function searchReadBatch(platform: App.Platform | undefined, statements: Statement[]): Promise<unknown[][]> {
  if (!statements.length) return [];
  const values = statements.map(parameters);
  const started = performance.now();
  if (building || dev) {
    const local = await localDatabase();
    return statements.map((statement, index) => local.prepare(statement.sql).all(...values[index]));
  }
  const client = platform?.readContext?.client ?? platform?.env.DB;
  if (!client) error(503, "Dataset database unavailable");
  if (statements.some((_, i) => values[i].length > 100)) throw new Error("Search statement exceeds D1 parameter limit");
  const prepared = statements.map((statement, index) => client.prepare(statement.sql).bind(...values[index]));
  const results = prepared.length === 1 ? [await prepared[0].all<unknown>()] : await client.batch<unknown>(prepared);
  if (results.length !== statements.length || results.some((result) => !result.success)) throw new Error("Search batch failed");
  const report = platform?.readContext?.report;
  results.forEach((result, index) => report?.({
    family: statements[index].family ?? "search", wall_ms: performance.now() - started,
    statements: results.length, rows_returned: result.results.length,
    rows_read: result.meta.rows_read, sql_ms: result.meta.timings?.sql_duration_ms ?? result.meta.duration,
    region: result.meta.served_by_region, primary: result.meta.served_by_primary,
  }));
  return results.map((result) => result.results);
}

export async function searchRead<S extends z.ZodType>(platform: App.Platform | undefined, schema: S, sql: string, values: readonly unknown[] = [], family = "search"): Promise<z.output<S>[]> {
  const [rows] = await searchReadBatch(platform, [{ sql, values, family }]);
  return schema.array().parse(rows);
}

/** Collect independent reads submitted in the same turn into native D1 batches. */
export function searchReadQueue(platform?: App.Platform, family = "facets") {
  let pending: { statement: Statement; resolve: (rows: unknown[]) => void; reject: (cause: unknown) => void }[] = [];
  let scheduled = false;
  const flush = async () => {
    scheduled = false;
    const jobs = pending;
    pending = [];
    try {
      const rows = await searchReadBatch(platform, jobs.map((job) => job.statement));
      jobs.forEach((job, index) => job.resolve(rows[index]));
    } catch (cause) { jobs.forEach((job) => job.reject(cause)); }
  };
  return async <S extends z.ZodType>(schema: S, sql: string, values: readonly unknown[] = []): Promise<z.output<S>[]> => {
    const rows = await new Promise<unknown[]>((resolve, reject) => {
      pending.push({ statement: { sql, values, family }, resolve, reject });
      if (!scheduled) { scheduled = true; queueMicrotask(flush); }
    });
    return schema.array().parse(rows);
  };
}
