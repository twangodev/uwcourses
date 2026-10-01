import { building, dev } from "$lib/server/runtime";
import { error } from "@sveltejs/kit";
import { drizzle } from "drizzle-orm/d1";
import { drizzle as proxy } from "drizzle-orm/sqlite-proxy";
import type { DatabaseSync } from "node:sqlite";
import type { BaseSQLiteDatabase } from "drizzle-orm/sqlite-core";
import * as schema from "./schema";

let local: DatabaseSync | undefined;
export async function localDatabase() {
  if (!local) {
    const moduleName = "node:sqlite";
    const { DatabaseSync }: typeof import("node:sqlite") = await import(/* @vite-ignore */ moduleName);
    local = new DatabaseSync(".site/import/site.sqlite", { readOnly: true });
  }
  return local;
}
const clients = new WeakMap<D1Database, ReturnType<typeof drizzle<typeof schema>>>();
const localClient = proxy(async (statement, params, method) => {
  if (method !== "all" && method !== "get" && method !== "values")
    throw new Error("The website database is read-only");
  const prepared = (await localDatabase()).prepare(statement);
  prepared.setReturnArrays(true);
  const array = (row: unknown): unknown[] => {
    if (!Array.isArray(row)) throw new Error("SQLite positional row expected");
    return row;
  };
  if (method === "get") {
    const row = prepared.get(...params);
    return { rows: row === undefined ? [] : array(row) };
  }
  return { rows: prepared.all(...params).map(array) };
}, { schema });
export function database(platform?: App.Platform): BaseSQLiteDatabase<"async", unknown, typeof schema> {
  if (building || dev) return localClient;
  const binding = platform?.env.DB;
  if (!binding) error(503, "Dataset database unavailable");
  let client = clients.get(binding);
  if (!client) { client = drizzle(binding, { schema }); clients.set(binding, client); }
  return client;
}

export function sqlValues(values: readonly unknown[]) {
  return values.map((value) => {
    if (value === null || typeof value === "string" || (typeof value === "number" && Number.isFinite(value))) return value;
    throw new Error("Invalid SQL parameter");
  });
}
