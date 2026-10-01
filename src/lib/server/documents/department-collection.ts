import type { DocumentContext } from "./types";
import { error } from "@sveltejs/kit";
import { searchCourses as search, query } from "$lib/server/data";
import {
  courseCollections,
  type CourseCollection,
} from "$lib/course-collections";
import entriesData from "../../../../.site/import/entries.json";
export async function department_collection({
  params,
  platform,
  url: currentUrl,
}: DocumentContext) {
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
  const url = new URL(currentUrl);
  url.searchParams.set("ranking", params.collection);
  url.searchParams.set("subject", params.subject);
  return {
    subject: params.subject,
    collection: params.collection,
    results: await search(url, platform),
  };
}
