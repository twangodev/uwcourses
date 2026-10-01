import { afterEach, describe, expect, it, vi } from "vitest";
import type { RequestEvent } from "@sveltejs/kit";
import {
  apiCacheUrl,
  cachedApiResponse,
} from "../../src/lib/server/response-cache";
afterEach(() => vi.unstubAllGlobals());
function setup(path: string) {
  const entries = new Map<string, Response>();
  const put = vi.fn(async (key: Request, response: Response) => {
    entries.set(key.url, response);
  });
  vi.stubGlobal("caches", {
    default: {
      match: async (key: Request) => entries.get(key.url)?.clone(),
      put,
    },
  });
  const writes: Promise<unknown>[] = [];
  const url = new URL(path, "https://uwcourses.com");
  const event = {
    url,
    request: new Request(url),
    isDataRequest: false,
    platform: {
      env: { SITE_COMMIT: "commit", DATA_PROJECTION: "projection" },
      context: {
        waitUntil: (promise: Promise<unknown>) => writes.push(promise),
      },
    },
  } as RequestEvent;
  return { event, writes, put };
}
describe("search API edge caching", () => {
  it("normalizes facet sets but preserves validation-sensitive duplicates and names", () => {
    const key = (query: string) =>
      apiCacheUrl(new URL(`https://uwcourses.com/api/facets?${query}`)).href;
    expect(
      key("facets=gpa,days&tags=small-lectures,higher-grades&page=2&sort=gpa"),
    ).toBe(key("tags=higher-grades,small-lectures&facets=days,gpa"));
    expect(key("facets=days,%20mode")).not.toBe(key("facets=days,mode"));
    expect(key("subject=COMPSCI,COMPSCI")).not.toBe(key("subject=COMPSCI"));
    expect(key("tags=" + Array(13).fill("small-lectures").join(","))).not.toBe(
      key("tags=small-lectures"),
    );
    expect(
      apiCacheUrl(
        new URL(
          "https://uwcourses.com/api/search?tags=higher-grades,small-lectures",
        ),
      ).search,
    ).not.toBe(
      apiCacheUrl(
        new URL(
          "https://uwcourses.com/api/search?tags=small-lectures,higher-grades",
        ),
      ).search,
    );
  });
  it("caches successful public requests for five minutes and isolates releases", async () => {
    const { event, writes, put } = setup("/api/facets?facets=gpa");
    const render = vi.fn(
      async () =>
        new Response("counts", {
          headers: { "Server-Timing": "facets;dur=12" },
        }),
    );
    const miss = await cachedApiResponse(event, render);
    await Promise.all(writes);
    expect(miss.headers.get("X-Cache")).toBe("MISS");
    expect(put.mock.calls[0][1].headers.get("Cache-Control")).toBe(
      "public, max-age=300",
    );
    const hit = await cachedApiResponse(event, render);
    expect(hit.headers.get("X-Cache")).toBe("HIT");
    expect(hit.headers.get("Cache-Control")).toBe("public, max-age=60");
    expect(hit.headers.get("Server-Timing")).toBe("cache;desc=HIT");
    expect(render).toHaveBeenCalledOnce();
    event.platform!.env.DATA_PROJECTION = "next";
    await cachedApiResponse(event, render);
    expect(render).toHaveBeenCalledTimes(2);
  });
  it("does not cache errors or credentialed requests", async () => {
    const { event, writes, put } = setup("/api/search");
    for (const status of [400, 409, 503])
      await cachedApiResponse(
        event,
        async () => new Response("error", { status }),
      );
    expect(put).not.toHaveBeenCalled();
    for (const headers of [
      { Cookie: "user=x" },
      { Authorization: "Bearer value" },
    ]) {
      event.request = new Request(event.url, { headers });
      await cachedApiResponse(event, async () => new Response("private"));
    }
    await Promise.all(writes);
    expect(put).not.toHaveBeenCalled();
  });
});
