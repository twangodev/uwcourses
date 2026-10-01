import { expect, test } from "@playwright/test";
import { documentSchemas, documentKind } from "../../../src/lib/api/schemas";

test("JSON document families satisfy the published contracts", async ({
  request,
}) => {
  for (const path of [
    "/index",
    "/courses/COMPSCI_300",
    "/courses/COMPSCI_400",
    "/courses/COMPSCI_759",
    "/instructors/HOBBES_LEGAULT",
    "/instructors/by-rating-count",
    "/departments",
    "/departments/COMPSCI",
    "/departments/ANAT%26PHY",
    "/departments/COMPSCI/catalog",
    "/departments/COMPSCI/easiest",
    "/courses/hardest",
    "/explorer/COMPSCI",
    "/search",
  ]) {
    const response = await request.get(path + ".json");
    expect(
      response.status(),
      path + ": " + (response.ok() ? "" : await response.text()),
    ).toBe(200);
    const document = await response.json();
    expect(
      documentSchemas[documentKind(path === "/index" ? "/" : path)].safeParse(
        document,
      ).success,
      path,
    ).toBe(true);
    expect(response.headers()["x-robots-tag"]).toBe("noindex");
    expect(response.headers()["access-control-allow-origin"]).toBe("*");
  }
});

test("HTML advertises representations; Markdown preserves model and citations", async ({
  request,
}) => {
  const path = "/courses/COMPSCI_300";
  const html = await request.get(path);
  expect(html.headers().link).toContain(path + ".md");
  const body = await html.text();
  expect(body).toContain('rel="alternate" type="application/json"');
  expect(body).toContain('rel="service-desc"');
  const json = await (await request.get(path + ".json")).json();
  const markdown = await request.get(path + ".md");
  expect(markdown.headers()["content-type"]).toContain("text/markdown");
  const text = await markdown.text();
  expect(text).toContain("Programming II");
  expect(text).toContain(json.data.course.llm_model);
  expect(text).toContain(json.dataset.revision);
  expect(text).toContain("requirements");
  const head = await request.head(path + ".md");
  expect(head.status()).toBe(200);
  expect(await head.text()).toBe("");
});

test("API discovery, aliases, query handling, errors and transport remain distinct", async ({
  request,
}) => {
  const spec = await (await request.get("/openapi.json")).json();
  expect(spec.openapi).toBe("3.1.0");
  expect(Object.keys(spec.paths)).toHaveLength(41);
  expect(spec.paths["/api/facets"].get.operationId).toBe("apiFacets");
  expect(spec.paths["/api/suggest"].get.operationId).toBe("apiSuggestions");
  expect(spec.paths["/api/weather"].get.operationId).toBe("madisonWeather");
  expect(spec.components.schemas.Course.properties.requirements).toBeTruthy();
  const query = await (await request.get("/search.json?q=java")).json();
  expect(query.data.results.q).toBe("java");
  const alias = await request.get("/courses/cs300.json", { maxRedirects: 0 });
  expect(alias.status()).toBe(308);
  expect(alias.headers().location).toBe("/courses/COMPSCI_300.json");
  for (const path of [
    "/courses/no-such-course.json",
    "/departments/NO_SUCH_DEPARTMENT.md",
  ]) {
    const response = await request.get(path);
    expect(response.status()).toBe(404);
    expect(response.headers()["cache-control"]).toBe("no-store");
  }
  expect((await request.get("/search.json?page=0")).status()).toBe(400);
  expect((await request.post("/search.json")).status()).toBe(405);
  const data = await request.get("/courses/COMPSCI_300/__data.json");
  expect(data.status()).toBe(200);
  expect((await data.json()).schema_version).toBeUndefined();
});

test("the existing interaction APIs satisfy their published schemas", async ({
  request,
}) => {
  const { interactionSchemas } = await import("../../../src/lib/api/schemas");
  const course = await (await request.get("/courses/COMPSCI_300.json")).json();
  const instructor = await (
    await request.get("/instructors/HOBBES_LEGAULT.json")
  ).json();
  const c = course.data.course.course_uid,
    i = instructor.data.instructor.instructor_uid;
  for (const [path, name] of [
    ["/api/status", "Status"],
    ["/api/search?q=java", "Search"],
    ["/api/suggest?q=java", "Suggestions"],
    [`/api/courses/${c}/grades`, "Grades"],
    [`/api/instructors/${i}/history`, "InstructorHistory"],
    [`/api/instructors/${i}/reviews`, "InstructorReviews"],
    [`/api/instructors/${i}/courses`, "InstructorCourses"],
  ] as const) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(200);
    expect(
      interactionSchemas[name].safeParse(await response.json()).success,
      path,
    ).toBe(true);
  }
  expect((await request.get("/api/search?revision=wrong")).status()).toBe(409);
  const options = await request.fetch("/courses/COMPSCI_300.json", {
    method: "OPTIONS",
  });
  expect(options.status()).toBe(204);
  expect(options.headers()["access-control-allow-headers"]).toContain(
    "If-None-Match",
  );
});

test("weather remains readable after the Worker cache is populated", async ({
  request,
}) => {
  for (let attempt = 0; attempt < 3; attempt++) {
    const response = await request.get("/api/weather");
    expect(response.status()).toBe(200);
    expect(response.headers()["x-robots-tag"]).toBe("noindex");
    expect(typeof (await response.json()).available).toBe("boolean");
  }
});

test("canonical URLs negotiate formats without changing browser or transport responses", async ({
  request,
}) => {
  const path = "/courses/COMPSCI_300";
  for (const [accept, type] of [
    ["text/markdown", "text/markdown"],
    ["application/json", "application/json"],
    ["text/html", "text/html"],
    ["text/markdown;q=0.2,text/html;q=0.9", "text/html"],
    ["*/*", "text/html"],
  ]) {
    const response = await request.get(path, { headers: { Accept: accept } });
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain(type);
    expect(response.headers().vary.toLowerCase()).toContain("accept");
    expect(await response.text()).toContain("Programming II");
  }
  const md = await request.get(path, { headers: { Accept: "text/markdown" } });
  expect(await md.text()).toBe(await (await request.get(path + ".md")).text());
  const head = await request.head(path, {
    headers: { Accept: "text/markdown" },
  });
  expect(head.headers()["content-type"]).toContain("text/markdown");
  expect(await head.text()).toBe("");
  const explicit = await request.get(path + ".json", {
    headers: { Accept: "text/markdown" },
  });
  expect(explicit.headers()["content-type"]).toContain("application/json");
  const transport = await request.get(path + "/__data.json", {
    headers: { Accept: "text/markdown" },
  });
  expect((await transport.json()).schema_version).toBeUndefined();
});
