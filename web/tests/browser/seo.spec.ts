import { expect, test } from "@playwright/test";

test("course metadata and catalog facts are in HTML before JavaScript runs", async ({
  request,
  browser,
}) => {
  const response = await request.get("/courses/COMPSCI_300?term=1264");
  expect(response.status()).toBe(200);
  const html = await response.text();
  expect(html).toMatch(
    /<link[^>]+rel="preload"[^>]+href="\/fonts\/OverusedGrotesk-VF\.woff2"[^>]+as="font"[^>]+crossorigin/,
  );
  expect(html).toContain("COMPSCI 300: Programming II | UW–Madison");
  const scripts = [
    ...html.matchAll(/<script type="application\/ld\+json">(.*?)<\/script>/gs),
  ];
  expect(scripts).toHaveLength(1);
  const graph = JSON.parse(scripts[0][1])["@graph"];
  expect(graph.find((item: any) => item["@type"] === "Course")).toMatchObject({
    courseCode: "COMPSCI 300",
    name: "Programming II",
    provider: { name: "University of Wisconsin–Madison" },
  });
  expect(
    graph.find((item: any) => item["@type"] === "BreadcrumbList")
      .itemListElement,
  ).toHaveLength(3);
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto(response.url());
  await expect(page.locator('link[rel="canonical"]')).toHaveCount(1);
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    "https://uwcourses.com/courses/COMPSCI_300",
  );
  await expect(
    page.getByRole("heading", { name: "Programming II", exact: true }),
  ).toBeVisible();
  await context.close();
});

test("client navigation replaces metadata without duplicate tags", async ({
  page,
}) => {
  await page.goto("/departments/COMPSCI/catalog");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await expect(page).toHaveTitle(
    /Computer Sciences Course Catalog.*UW–Madison/,
  );
  await page.locator('.catalog a[href="/courses/COMPSCI_300"]').click();
  await expect(page).toHaveTitle("COMPSCI 300: Programming II | UW–Madison");
  await expect(page.locator('meta[name="description"]')).toHaveCount(1);
  await expect(page.locator('link[rel="canonical"]')).toHaveCount(1);
  await expect(page.locator('meta[property="og:url"]')).toHaveAttribute(
    "content",
    "https://uwcourses.com/courses/COMPSCI_300",
  );
  await expect(page.locator('script[type="application/ld+json"]')).toHaveCount(
    1,
  );
  await expect
    .poll(() =>
      page.locator('script[type="application/ld+json"]').textContent(),
    )
    .toContain('"courseCode":"COMPSCI 300"');
});

test("robots permits search, AI answers and training", async ({ request }) => {
  const response = await request.get("/robots.txt");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("text/plain");
  const directives = (await response.text())
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
  expect(directives).toEqual([
    "User-agent: *",
    "Content-Signal: search=yes, ai-input=yes, ai-train=yes",
    "Allow: /",
    "Sitemap: https://uwcourses.com/sitemap.xml",
  ]);
});

test("sitemaps, redirects, errors and search expose the intended crawl policy", async ({
  request,
}) => {
  const index = await request.get("/sitemap.xml");
  expect(index.status()).toBe(200);
  expect(index.headers()["content-type"]).toContain("application/xml");
  const xml = await index.text();
  expect(xml).toMatch(/<lastmod>\d{4}-\d{2}-\d{2}T/);
  const locations = [
    ...xml.matchAll(/<loc>https:\/\/uwcourses.com([^<]+)<\/loc>/g),
  ].map((match) => match[1]);
  expect(locations.length).toBeGreaterThan(2);
  for (const location of locations) {
    const response = await request.get(location);
    expect(response.status()).toBe(200);
    const sitemap = await response.text();
    expect(sitemap).toContain("<urlset");
    if (location === "/blog/sitemap.xml") {
      expect(sitemap).toContain("<loc>https://uwcourses.com/blog</loc>");
      for (const [, date] of sitemap.matchAll(/<lastmod>([^<]+)<\/lastmod>/g)) {
        expect(date).toMatch(/^\d{4}-\d{2}-\d{2}(?:T[^<]+)?$/);
        expect(Number.isNaN(Date.parse(date))).toBe(false);
      }
    } else {
      expect(sitemap).toMatch(/<lastmod>\d{4}-\d{2}-\d{2}T/);
      expect(sitemap).toContain("<priority>");
      expect(sitemap).toContain("<changefreq>");
    }
  }
  for (const path of ["/subjects", "/stats/COMPSCI"]) {
    const response = await request.get(path + "?term=1264", {
      maxRedirects: 0,
    });
    expect(response.status()).toBe(308);
    expect(response.headers().location).toBe(
      (path.endsWith("COMPSCI") ? "/departments/COMPSCI" : "/departments") +
        "?term=1264",
    );
  }
  for (const [path, status] of [
    ["/courses/nonexistent-999", 404],
    ["/search?q=CS300", 200],
  ] as const) {
    const response = await request.get(path);
    expect(response.status()).toBe(status);
    expect(await response.text()).toMatch(
      /name="robots" content="noindex,follow"/,
    );
  }
  expect((await request.get("/api/status")).headers()["x-robots-tag"]).toBe(
    "noindex",
  );
});

test("course-list sources link to a real course section without JavaScript", async ({
  browser,
  baseURL,
}) => {
  const context = await browser.newContext({
    javaScriptEnabled: false,
    baseURL,
  });
  const page = await context.newPage();
  await page.goto("/departments/COMPSCI");
  const source = page
    .getByRole("link", { name: "Sources", exact: true })
    .first();
  await expect(source).toHaveAttribute("href", /^\/courses\/.+#evidence$/);
  await source.click();
  await expect(page).toHaveURL(/\/courses\/.+#evidence$/);
  await expect(page.locator("#evidence")).toHaveCount(1);
  await context.close();
});

test("instructor HTML describes its named person and hydration JSON stays out of search", async ({
  request,
}) => {
  const response = await request.get("/instructors/HOBBES_LEGAULT");
  expect(response.status()).toBe(200);
  const html = await response.text();
  const graph = JSON.parse(
    html.match(/<script type="application\/ld\+json">(.*?)<\/script>/s)![1],
  )["@graph"];
  const person = graph.find((item: any) => item["@type"] === "Person");
  expect(person).toMatchObject({
    name: "Hobbes Legault",
    "@id": "https://uwcourses.com/instructors/HOBBES_LEGAULT#person",
  });
  expect(
    graph.find((item: any) => item["@type"] === "WebPage").mainEntity,
  ).toEqual({ "@id": person["@id"] });
  for (const path of [
    "/__data.json",
    "/courses/COMPSCI_300/__data.json",
    "/instructors/HOBBES_LEGAULT/__data.json",
  ]) {
    const data = await request.get(path);
    expect(data.status()).toBe(200);
    expect(data.headers()["x-robots-tag"]).toBe("noindex");
    expect(data.headers()["content-type"]).toContain("application/json");
  }
  expect(response.headers()["x-robots-tag"]).toBeUndefined();
});

test("discovery landing pages are indexable while query variants remain excluded", async ({
  request,
}) => {
  for (const path of ["/search", "/instructors/by-rating-count"]) {
    const response = await request.get(path);
    expect(response.status()).toBe(200);
    const html = await response.text();
    expect(html).toContain('name="robots" content="index,follow');
    expect(html).toContain(
      `rel="canonical" href="https://uwcourses.com${path}"`,
    );
    for (const query of ["?q=300", "?page=2"]) {
      const filtered = await request.get(path + query);
      expect(filtered.status()).toBe(200);
      expect(await filtered.text()).toContain(
        'name="robots" content="noindex,follow"',
      );
    }
  }
});

test("social cards match page families and serve valid 1200 by 630 PNGs", async ({
  request,
}) => {
  for (const [path, kind] of [
    ["/courses/COMPSCI_300", "courses"],
    ["/instructors/HOBBES_LEGAULT", "instructors"],
    ["/departments/COMPSCI", "departments"],
    ["/explorer/COMPSCI", "maps"],
  ]) {
    const html = await (await request.get(path)).text();
    expect(html).toContain(
      `property="og:image" content="https://uwcourses.com/social/pages${path}.png"`,
    );
    expect(html).toContain('name="twitter:card" content="summary_large_image"');
    expect(html).toContain('property="og:image:alt" content="UW Courses');
    const response = await request.get(`/social/pages${path}.png`);
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("image/png");
    const png = await response.body();
    expect(png.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
    expect(png.readUInt32BE(16)).toBe(1200);
    expect(png.readUInt32BE(20)).toBe(630);
    expect(png.length).toBeLessThan(300_000);
  }
});
