import { primaryDatabase } from "./database";
import { drizzle } from "drizzle-orm/d1";
import * as schema from "./schema";
import type { SearchReadContext, QueryMeasurement } from "./search-reader";

/** Drizzle 0.45 accepts full bindings; this facade explicitly supplies its contract. */
export function sessionDriver(session: D1DatabaseSession): D1Database {
  return {
    prepare: (statement) => session.prepare(statement),
    batch: (statements) => session.batch(statements),
    exec: async () => {
      throw new Error(
        "Direct execution is unavailable on the search session adapter",
      );
    },
    dump: async () => {
      throw new Error(
        "Database dumps are unavailable on the search session adapter",
      );
    },
    withSession: () => {
      throw new Error("Create search sessions at the request boundary");
    },
  };
}

export function createSearchReadContext(
  binding: D1Database,
  mode: "primary" | "session" = "primary",
  report?: (measurement: QueryMeasurement) => void,
): SearchReadContext {
  const client =
    mode === "session"
      ? sessionDriver(binding.withSession("first-primary"))
      : binding;
  return {
    client,
    orm:
      mode === "session"
        ? drizzle(client, { schema })
        : primaryDatabase(binding),
    report,
  };
}

/** Clone request platform state; shared Worker bindings must never retain a session. */
export function searchRequestPlatform(platform: App.Platform): App.Platform {
  const report =
    platform.env.D1_QUERY_LOGS === "1"
      ? (measurement: QueryMeasurement) => {
          console.info("search-query", {
            projection: platform.env.DATA_PROJECTION,
            ...measurement,
          });
        }
      : undefined;
  return {
    ...platform,
    readContext: createSearchReadContext(
      platform.env.DB,
      platform.env.D1_READ_MODE ?? "primary",
      report,
    ),
  };
}
