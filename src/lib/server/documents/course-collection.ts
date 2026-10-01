import type { DocumentContext } from "./types";
import { searchCourses as search } from "$lib/server/data";
import {
  courseCollections,
  type CourseCollection,
} from "$lib/course-collections";
export async function course_collection({ params, platform }: DocumentContext) {
  const url = new URL("http://prerender/search");
  url.searchParams.set("ranking", params.collection);
  return {
    collection: params.collection,
    subject: "",
    results: await search(url, platform),
  };
}
