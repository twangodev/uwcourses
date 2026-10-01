import { schoolStatsSchema } from "$lib/school-stats";
import { selectStatsTerm } from "./stats-selection";
import { error, redirect } from "@sveltejs/kit";
import type { PublicDocument } from "$lib/api/schemas";
import { normalize } from "$lib/format";

// Keep historical instructor profiles without one asset per historical identity.
export const instructorBuckets = 4096;
export function instructorBucket(path: string) {
  let hash = 2166136261;
  for (const letter of path)
    hash = Math.imul(hash ^ letter.charCodeAt(0), 16777619);
  return ((hash >>> 0) % instructorBuckets).toString(16).padStart(3, "0");
}
export function documentAsset(path: string) {
  if (path.startsWith("/stats?")) {
    const term = new URL(path, "https://uwcourses.com").searchParams.get(
      "term",
    );
    if (term !== null) {
      if (!/^1\d{2}[246]$/.test(term)) error(400, "Unknown statistics term");
      return `/__documents/statistics/${term}.json`;
    }
    return "/__documents/pages/stats.json";
  }
  return path.startsWith("/instructors/") &&
    path !== "/instructors/by-rating-count"
    ? `/__documents/instructors/${instructorBucket(path)}.json`
    : `/__documents/pages${path === "/" ? "/index" : path}.json`;
}
export async function readAsset<T>(
  path: string,
  platform?: App.Platform,
): Promise<T | null> {
  if (!platform?.env.ASSETS) error(503, "Published documents unavailable");
  const response = await platform.env.ASSETS.fetch(
    new Request(new URL(path, "https://assets.internal")),
  );
  if (response.status === 404) return null;
  if (!response.ok) error(503, "Published document could not be read");
  return response.json() as Promise<T>;
}
export function isFilteredDocument(url: URL) {
  return (
    (url.pathname === "/search" ||
      url.pathname === "/instructors/by-rating-count" ||
      /^\/departments\/[^/]+(?:\/(?:easiest|hardest))?\/?$/.test(
        url.pathname,
      ) ||
      /^\/courses\/(?:easiest|hardest)\/?$/.test(url.pathname)) &&
    url.searchParams.size > 0
  );
}
export async function readDocument(
  url: URL,
  platform?: App.Platform,
): Promise<PublicDocument> {
  let path: string;
  try {
    path = url.pathname
      .split("/")
      .map((part) => encodeURIComponent(decodeURIComponent(part)))
      .join("/");
  } catch {
    error(400, "Invalid document URL");
  }
  const stored = await readAsset<
    PublicDocument | Record<string, PublicDocument>
  >(documentAsset(path === "/stats" ? path + url.search : path), platform);
  const grouped =
    path.startsWith("/instructors/") && path !== "/instructors/by-rating-count";
  const document = grouped
    ? (stored as Record<string, PublicDocument> | null)?.[path]
    : (stored as PublicDocument | null);
  if (document) {
    if (path === "/stats" && "schoolStats" in document.data)
      return {
        ...document,
        url: new URL(path + url.search, "https://uwcourses.com").href,
        data: {
          schoolStats: selectStatsTerm(
            schoolStatsSchema.parse(document.data.schoolStats),
            url,
          ),
        },
      };
    return document;
  }
  if (path === "/stats") error(400, "Unknown statistics term");
  // Aliases only need the small routing index on a miss; normal pages read one asset.
  const routes = await readAsset<{
    courses: Record<string, string>;
    instructors: Record<string, string>;
    subjects: string[];
  }>("/__documents/redirects.json", platform);
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "courses" && !parts[1]?.startsWith("course_")) {
    const target = routes?.courses[normalize(parts[1] || "")];
    if (typeof target === "string" && target !== path)
      redirect(
        target.startsWith("/search?") ? 307 : 308,
        target + (target.includes("?") ? "" : url.search),
      );
  }
  if (parts[0] === "instructors") {
    const target = routes?.instructors[parts[1]];
    if (typeof target === "string" && target !== path)
      redirect(308, target + url.search);
  }
  if (
    (parts[0] === "departments" || parts[0] === "explorer") &&
    routes?.subjects.includes(parts[1]?.toUpperCase())
  ) {
    parts[1] = parts[1].toUpperCase();
    const target = "/" + parts.map(encodeURIComponent).join("/");
    if (target !== path) redirect(308, target + url.search);
  }
  error(404, "Document not found");
}
