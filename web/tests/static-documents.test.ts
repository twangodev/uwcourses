import { describe, expect, it, vi } from "vitest";
vi.mock("$app/environment", () => ({ building: false, dev: false }));
import {
  documentAsset,
  instructorBucket,
  readDocument,
  isFilteredDocument,
} from "../../src/lib/server/documents/storage";
import { pageDocument } from "../../src/lib/server/documents/page";

import { courseContexts } from "../../src/lib/server/course-context";
import { departmentStats } from "../../src/lib/server/departments";
import { gradeSummary } from "../../src/lib/discovery";

const document = {
  schema_version: 1,
  url: "https://uwcourses.com/courses/COMPSCI_300",
  title: "Programming II",
  dataset: { revision: "test" },
  data: {
    course: { course_id: "COMPSCI 300" },
    context: { precomputed: true },
  },
};
function platform(files: Record<string, unknown>) {
  const fetch = vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname;
    return path in files
      ? Response.json(files[path])
      : new Response(null, { status: 404 });
  });
  const env = new Proxy(
    { ASSETS: { fetch } },
    {
      get(target, key) {
        if (key === "DB") throw new Error("Page attempted a database read");
        return Reflect.get(target, key);
      },
    },
  );
  return { platform: { env } as unknown as App.Platform, fetch };
}
const context = (path: string, env: App.Platform) => ({
  url: new URL(path, "https://uwcourses.com"),
  params: {},
  platform: env,
  setHeaders: () => {},
});

describe("static page documents", () => {
  it("reuses published department statistics without reading D1, including empty grade histories", async () => {
    const summary = gradeSummary([]);
    const stats = {
      all: {
        ...summary,
        university: summary,
        courses: null,
        instructors: 0,
        levels: [],
      },
      terms: {},
    };
    const { platform: env, fetch } = platform({
      [documentAsset("/departments/ANAT%26PHY")]: { data: { stats } },
    });
    expect(await departmentStats("ANAT&PHY", env)).toEqual(stats);
    expect(fetch).toHaveBeenCalledOnce();
    await expect(departmentStats("MISSING", env)).rejects.toMatchObject({
      status: 503,
    });
  });
  it("serves SSR and public data from the same generated document without querying D1", async () => {
    const { platform: env, fetch } = platform({
      [documentAsset("/courses/COMPSCI_300")]: document,
    });
    const source = vi.fn(async () => ({ dynamic: true }));
    const ctx = context("/courses/COMPSCI_300?term=1272", env);
    const page = await pageDocument(source)(ctx);
    const api = await readDocument(ctx.url, env);
    expect(page).toEqual(api.data);
    expect(source).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it.each([
    "/search?q=java",
    "/departments/COMPSCI?days=mon&days_match=any",
    "/departments/COMPSCI?term=1264",
    "/courses/easiest?credits_min=3",
    "/courses/hardest?tags=small-lectures",
    "/departments/COMPSCI/easiest?gpa_min=3",
    "/departments/COMPSCI/hardest?mode=in_person",
  ])("keeps filtered finder documents live at %s", async (path) => {
    const { platform: env, fetch } = platform({});
    const source = vi.fn(async () => ({ query: true }));
    expect(await pageDocument(source)(context(path, env))).toEqual({
      query: true,
    });
    expect(source).toHaveBeenCalledOnce();
    expect(fetch).not.toHaveBeenCalled();
    const unfiltered = new URL(path, "https://uwcourses.com");
    unfiltered.search = "";
    expect(isFilteredDocument(unfiltered)).toBe(false);
  });
  it("selects only the requested instructor from a bucket", async () => {
    const path = "/instructors/HOBBES_LEGAULT";
    const profile = {
      ...document,
      url: "https://uwcourses.com" + path,
      data: { instructor: { name: "Hobbes Legault" } },
    };
    const { platform: env } = platform({
      [documentAsset(path)]: {
        [path]: profile,
        "/instructors/OTHER": document,
      },
    });
    expect(await readDocument(context(path, env).url, env)).toEqual(profile);
    expect(instructorBucket(path)).toMatch(/^[0-9a-f]{3}$/);
    expect(documentAsset("/instructors/by-rating-count")).toContain("/pages/");
  });
  it("normalizes equivalent URL encodings before selecting a document", async () => {
    const path = "/departments/ANAT%26PHY";
    const { platform: env } = platform({ [documentAsset(path)]: document });
    for (const input of [
      path,
      "/departments/ANAT&PHY",
      "/departments/ANAT%26PHY",
    ]) {
      expect(await readDocument(context(input, env).url, env)).toEqual(
        document,
      );
    }
  });
  it("preserves aliases and unknown-page errors without a database fallback", async () => {
    const { platform: env } = platform({
      "/__documents/redirects.json": {
        courses: { COMPSCI300: "/courses/COMPSCI_300" },
        instructors: {},
        subjects: ["COMPSCI"],
      },
    });
    await expect(
      readDocument(context("/courses/cs300?term=1272", env).url, env),
    ).rejects.toMatchObject({
      status: 308,
      location: "/courses/COMPSCI_300?term=1272",
    });
    await expect(
      readDocument(context("/courses/missing", env).url, env),
    ).rejects.toMatchObject({ status: 404 });
  });
  it("uses precomputed comparisons for search cards without reading grade histories", async () => {
    const precomputed = { all: { gpa: 3.2 }, terms: {}, benchmarks: {} };
    const { platform: env } = platform({
      "/__documents/contexts/course-one.json": { context: precomputed },
    });
    const course = {
      course_uid: "course-one",
      get grades() {
        throw new Error("Grade history scanned at runtime");
      },
    };
    expect((await courseContexts([course], env)).get("course-one")).toEqual(
      precomputed,
    );
    await expect(
      courseContexts([{ course_uid: "missing" }], env),
    ).rejects.toMatchObject({ status: 503 });
  });
  it("does not turn asset outages into a database scan or a 404", async () => {
    const env = {
      env: {
        ASSETS: { fetch: async () => new Response(null, { status: 500 }) },
      },
    } as unknown as App.Platform;
    await expect(
      readDocument(context("/courses/COMPSCI_300", env).url, env),
    ).rejects.toMatchObject({ status: 503 });
  });
});

it("resolves only the requested instructor URL shards and rating prior without D1", async () => {
  const { withInstructorUrls, instructorUrlAsset } =
    await import("../../src/lib/server/instructor-urls");
  const { instructorRatingPrior } =
    await import("../../src/lib/server/instructor-ratings");
  const uid = "instructor_example";
  const { platform: env, fetch } = platform({
    [instructorUrlAsset(uid)]: {
      [uid]: "/instructors/EXAMPLE--instructor_example",
    },
    "/__documents/search-metadata.json": { mean: 3.7 },
  });
  const rows = await withInstructorUrls([{ instructor_uid: uid }], env);
  expect(rows[0].instructor_url).toBe(
    "/instructors/EXAMPLE--instructor_example",
  );
  expect(await instructorRatingPrior(env)).toBe(3.7);
  expect(fetch).toHaveBeenCalledTimes(2);
  await expect(
    withInstructorUrls([{ instructor_uid: "missing" }], env),
  ).rejects.toMatchObject({ status: 503 });
});
