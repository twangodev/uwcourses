import { error } from "@sveltejs/kit";
import { inArray } from "drizzle-orm";
import { database } from "./database";
import { metadata } from "./schema";
import publishedStatus from "../../../.site/import/status.json";

/** Page documents stay available while a single D1 is replaced in place. */
export async function withDatabaseAvailability<T>(
  platform: App.Platform | undefined,
  render: () => Promise<T>,
) {
  const check = async (primary = false) => {
    let token: string | undefined;
    try {
      const rows = await database(platform, primary)
        .select()
        .from(metadata)
        .where(inArray(metadata.key, ["ready", "status", "serving"]));
      const state = Object.fromEntries(rows.map((row) => [row.key, row.value]));
      if (
        state.ready === "true" &&
        /^[a-f0-9]{32}$/.test(state.serving || "") &&
        JSON.parse(state.status).projection_id === publishedStatus.projection_id
      )
        token = state.serving;
    } catch {
      /* Missing metadata is expected while the schema is replaced. */
    }
    if (!token)
      error(503, "Search and filters are updating. Please try again shortly.");
    return token;
  };
  const token = await check();
  try {
    const response = await render();
    // Do not return a result if an import started during its queries.
    if ((await check(true)) !== token)
      error(503, "Search was updated during this request. Please try again.");
    return response;
  } catch (cause) {
    if ((await check(true)) !== token)
      error(503, "Search was updated during this request. Please try again.");
    throw cause;
  }
}
