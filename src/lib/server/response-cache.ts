import type { RequestEvent } from "@sveltejs/kit";

/** A release-addressed key prevents serving an old projection after a deployment. */
export function responseCacheKey(url: URL, release: string, format = "html") {
  const key = new URL(url);
  key.searchParams.sort();
  key.pathname =
    "/__response-cache/" +
    encodeURIComponent(release) +
    "/" +
    format +
    key.pathname;
  return new Request(key);
}
export async function cachedResponse(
  event: RequestEvent,
  render: () => Promise<Response>,
  format = "html",
  options: { url?: URL; ttl?: number; clientCacheControl?: string } = {},
) {
  const env = event.platform?.env;
  const release =
    env?.SITE_COMMIT && env.DATA_PROJECTION
      ? `${env.SITE_COMMIT}:${env.DATA_PROJECTION}`
      : null;
  // Navigation transport depends on invalidation headers. Never share it with documents.
  if (
    !release ||
    !event.platform ||
    event.isDataRequest ||
    event.request.method !== "GET" ||
    event.request.headers.has("authorization") ||
    event.request.headers.has("cookie")
  )
    return render();
  const cache = (caches as CacheStorage & { default: Cache }).default;
  const key = responseCacheKey(options.url ?? event.url, release, format);
  const hit = await cache.match(key);
  const respond = (response: Response, state: string) => {
    const headers = new Headers(response.headers);
    headers.set(
      "Cache-Control",
      options.clientCacheControl ?? "public, max-age=0, must-revalidate",
    );
    if (format === "api" && state === "HIT")
      headers.set("Server-Timing", "cache;desc=HIT");
    headers.set("X-Cache", state);
    if (event.request.headers.get("if-none-match") === headers.get("etag"))
      return new Response(null, { status: 304, headers });
    return new Response(response.body, { status: response.status, headers });
  };
  if (hit) return respond(hit, "HIT");
  const response = await render();
  if (
    response.status !== 200 ||
    response.headers.has("set-cookie") ||
    /private|no-store/i.test(response.headers.get("cache-control") || "")
  )
    return response;
  const body = await response.arrayBuffer();
  const headers = new Headers(response.headers);
  const digest = await crypto.subtle.digest("SHA-256", body);
  headers.set(
    "ETag",
    '"' +
      Array.from(new Uint8Array(digest), (b) =>
        b.toString(16).padStart(2, "0"),
      ).join("") +
      '"',
  );
  headers.set("Cache-Control", `public, max-age=${options.ttl ?? 86400}`);
  const stored = new Response(body, { headers });
  event.platform.context.waitUntil(
    cache
      .put(key, stored.clone())
      .catch((error) => console.error("Response cache write failed", error)),
  );
  return respond(stored, "MISS");
}

const searchApiPaths = new Set(["/api/search", "/api/facets", "/api/suggest"]);
export function isSearchApi(path: string) {
  return searchApiPaths.has(path);
}

export function apiCacheUrl(url: URL) {
  const key = new URL(url);
  if (key.pathname === "/api/facets") {
    key.searchParams.delete("page");
    key.searchParams.delete("sort");
    const tokenParams = new Set([
      "subject",
      "tags",
      "level",
      "season",
      "designation",
      "days",
      "time",
      "mode",
    ]);
    const entries = [...key.searchParams].map(
      ([name, value]) =>
        [
          name,
          name === "facets"
            ? value.split(",").sort().join(",")
            : tokenParams.has(name)
              ? value
                  .split(",")
                  .map((token) => token.trim())
                  .filter(Boolean)
                  .sort()
                  .join(",")
              : name === "q"
                ? value.trim()
                : value,
        ] as const,
    );
    key.search = "";
    for (const [name, value] of entries) key.searchParams.append(name, value);
  }
  // Search/suggest echo raw filters, so preserve their values and duplicate ordering.
  key.searchParams.sort();
  return key;
}
export function cachedApiResponse(
  event: RequestEvent,
  render: () => Promise<Response>,
) {
  if (!isSearchApi(event.url.pathname)) return render();
  return cachedResponse(event, render, "api", {
    url: apiCacheUrl(event.url),
    ttl: 300,
    clientCacheControl: "public, max-age=60",
  });
}
