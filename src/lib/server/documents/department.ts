import type { DocumentContext } from "./types";
import { building } from "$lib/server/runtime";
import { error, redirect } from "@sveltejs/kit";
import { query, searchCourses as search } from "$lib/server/data";
import { departmentStats } from "$lib/server/departments";
import entriesData from "../../../../.site/import/entries.json";

export async function department({ params, platform, url }: DocumentContext) {
  if (params.subject !== params.subject.toUpperCase())
    redirect(
      308,
      url.pathname.slice(0, url.pathname.lastIndexOf("/") + 1) +
        encodeURIComponent(params.subject.toUpperCase()) +
        (building ? "" : url.search),
    );
  if (
    !(
      await query(
        platform,
        "SELECT uid FROM subjects WHERE subject=? LIMIT 1",
        [params.subject],
      )
    ).length
  )
    error(404, "Department not found");
  const searchUrl = new URL("http://prerender/search");
  searchUrl.searchParams.set("subject", params.subject);
  searchUrl.searchParams.set("kind", "course");
  const [results, stats] = await Promise.all([
    search(searchUrl, platform),
    departmentStats(params.subject, platform),
  ]);
  return { subject: params.subject, results, stats };
}
