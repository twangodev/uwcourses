import { test, expect, type Page, type Response } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

const chart = (page: Page, label: string) =>
  page.locator(`.facet-chart[aria-label="${label} distribution"]`);
const responseFor = (
  page: Page,
  facet: string,
  params: Record<string, string> = {},
) =>
  page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === "/api/facets" &&
      (url.searchParams.get("facets") || "").split(",").includes(facet) &&
      Object.entries(params).every(
        ([key, value]) => url.searchParams.get(key) === value,
      )
    );
  });
async function body(response: Response) {
  expect(response.status()).toBe(200);
  return response.json();
}

test("GPA responds while typing and compares all results with a stable contextual distribution", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const initial = responseFor(page, "gpa");
  await page.getByRole("button", { name: "Grades", exact: true }).click();
  const before = (await body(await initial)).distributions.gpa;
  const histogram = chart(page, "Historical GPA");
  expect(before.bins).toHaveLength(40);
  const plotted = await histogram
    .locator('rect[fill="var(--muted)"]')
    .evaluateAll((bars) => bars.map((bar) => bar.getAttribute("data-value")));
  expect(plotted.length).toBeGreaterThan(8);
  expect(plotted.length).toBeLessThan(40);
  const axis = await histogram.locator(".numeric-axis span").allTextContents();
  expect(Number(axis[0])).toBeGreaterThan(0);
  expect(axis.at(-1)).toBe("4.0");
  const gray = await histogram
    .locator('rect[fill="var(--muted)"]')
    .evaluateAll((bars) => bars.map((bar) => bar.getAttribute("height")));
  expect(before.total).toBeGreaterThan(30);
  const updated = responseFor(page, "gpa", { gpa_min: "3.5" });
  const input = page.getByRole("spinbutton", {
    name: "Historical GPA at least",
  });
  await input.fill("3.5");
  const after = (await body(await updated)).distributions.gpa;
  await expect(page).toHaveURL(/gpa_min=3\.5/);
  await expect(input).toBeFocused();
  await expect(page.locator(".panel-content")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  expect(after.total).toBe(before.total);
  expect(after.bins.map((bin: any) => bin.count)).toEqual(
    before.bins.map((bin: any) => bin.count),
  );
  expect(after.matched).toBeLessThan(before.matched);
  expect(
    await histogram.locator(".numeric-axis span").allTextContents(),
  ).toEqual(axis);
  expect(
    await histogram
      .locator('rect[fill="var(--muted)"]')
      .evaluateAll((bars) => bars.map((bar) => bar.getAttribute("height"))),
  ).toEqual(gray);
  const params = new URL(page.url()).searchParams;
  const search = await page.request.get(`/api/search?${params}`);
  expect((await search.json()).total).toBe(after.matched);
  await page.locator(".filter-panel").screenshot({
    path: "/tmp/course-facets-live-gpa.png",
    animations: "disabled",
  });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    const labels = await histogram
      .locator(".numeric-axis span")
      .evaluateAll((nodes) =>
        nodes.map((node) => {
          const bounds = node.getBoundingClientRect();
          return { left: bounds.left, right: bounds.right };
        }),
      );
    expect(
      labels.every(
        (label, index) => index === 0 || label.left > labels[index - 1].right,
      ),
    ).toBe(true);
  }
  expect(errors).toEqual([]);
});

test("categorical graphs are selectable and change when another filter changes", async ({
  page,
}) => {
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const initial = responseFor(page, "level");
  await page
    .getByRole("button", { name: "Course details", exact: true })
    .click();
  const before = (await body(await initial)).distributions.level;
  const updated = responseFor(page, "level", { level: "300" });
  await chart(page, "Course numbers")
    .getByRole("button", { name: "300–399", exact: true })
    .click();
  const selected = (await body(await updated)).distributions.level;
  await expect(page).toHaveURL(/level=300/);
  expect(selected.bins.map((bin: any) => bin.count)).toEqual(
    before.bins.map((bin: any) => bin.count),
  );
  expect(
    selected.bins
      .filter((bin: any) => bin.matched > 0)
      .map((bin: any) => bin.value),
  ).toEqual(["300"]);
  const narrowed = responseFor(page, "level", { credits_min: "4" });
  await page.getByRole("spinbutton", { name: "Credits at least" }).fill("4");
  const credits = (await body(await narrowed)).distributions.level;
  expect(credits.total).toBeLessThan(before.total);
  await expect(page.locator(".panel-content")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await page.locator(".filter-panel").screenshot({
    path: "/tmp/course-facets-live-details.png",
    animations: "disabled",
  });
});

test("department dropdown and open filter panel both stay live and fit mobile", async ({
  page,
}) => {
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const initial = responseFor(page, "gpa");
  await page.getByRole("button", { name: "Grades", exact: true }).click();
  await body(await initial);
  const opened = responseFor(page, "subject");
  await page.getByRole("button", { name: "Department", exact: true }).click();
  await body(await opened);
  await expect(chart(page, "Department").locator(".plot svg")).toBeVisible();
  await expect(
    chart(page, "Historical GPA").locator(".plot svg"),
  ).toBeVisible();
  const changed = responseFor(page, "gpa", { subject: "MATH" });
  await page
    .getByRole("option", { name: "Mathematics (MATH)", exact: true })
    .click();
  await body(await changed);
  await expect(page).toHaveURL(/subject=MATH/);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".panel-content")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  const schedule = responseFor(page, "days");
  await page.getByRole("button", { name: "Schedule", exact: true }).click();
  await body(await schedule);
  await expect(chart(page, "Class days").locator(".plot svg")).toBeVisible();
  await expect(
    chart(page, "Instruction mode").locator(".plot svg"),
  ).toBeVisible();
  await page.locator(".filter-panel").screenshot({
    path: "/tmp/course-facets-mobile.png",
    animations: "disabled",
  });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("failed distributions show a recoverable error and revision mismatches fail clearly", async ({
  page,
}) => {
  await page.goto("/search?subject=COMPSCI");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await page.route("**/api/facets?*", (route) =>
    route.fulfill({ status: 503, body: "unavailable" }),
  );
  await page.getByRole("button", { name: "Grades", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Distributions are unavailable",
  );
  await page.unroute("**/api/facets?*");
  const recovered = responseFor(page, "gpa", { gpa_min: "3" });
  await page
    .getByRole("spinbutton", { name: "Historical GPA at least" })
    .fill("3");
  await body(await recovered);
  await expect(
    chart(page, "Historical GPA").locator(".plot svg"),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(
    (
      await page.request.get("/api/facets?revision=outdated&facets=gpa")
    ).status(),
  ).toBe(409);
});

test("a delayed response cannot overwrite a newer filter choice", async ({
  page,
}) => {
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const initial = responseFor(page, "gpa");
  await page.getByRole("button", { name: "Grades", exact: true }).click();
  await body(await initial);
  let release!: () => void;
  let handled!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const completed = new Promise<void>((resolve) => {
    handled = resolve;
  });
  await page.route("**/api/facets?*", async (route) => {
    if (new URL(route.request().url()).searchParams.get("gpa_min") !== "3") {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    await gate;
    try {
      await route.fulfill({ response });
    } finally {
      handled();
    }
  });
  const firstRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return (
      url.pathname === "/api/facets" && url.searchParams.get("gpa_min") === "3"
    );
  });
  const input = page.getByRole("spinbutton", {
    name: "Historical GPA at least",
  });
  await input.fill("3");
  await firstRequest;
  const latest = responseFor(page, "gpa", { gpa_min: "3.5" });
  await input.fill("3.5");
  await body(await latest);
  await expect(page.locator(".panel-content")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  const bars = chart(page, "Historical GPA").locator(
    'rect[fill="var(--accent)"]',
  );
  const heights = await bars.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("height")),
  );
  release();
  await completed;
  await expect(input).toHaveValue("3.5");
  expect(
    await bars.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("height")),
    ),
  ).toEqual(heights);
});

test("loading keeps filter controls stable and the desktop layout uses its width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/facets?*", async (route) => {
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
  });
  const loaded = responseFor(page, "level");
  await page
    .getByRole("button", { name: "Course details", exact: true })
    .click();
  const input = page.getByRole("spinbutton", { name: "Credits at least" });
  const before = await input.boundingBox();
  const first = chart(page, "Course numbers").getByRole("button", {
    name: "300–399",
    exact: true,
  });
  await first.focus();
  release();
  await body(await loaded);
  await expect(page.locator(".panel-content")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await expect(first).toBeFocused();
  const after = await input.boundingBox();
  expect(Math.abs(after!.y - before!.y)).toBeLessThan(1);
  const panel = await page.locator(".filter-panel").boundingBox();
  expect(panel!.height).toBeLessThan(500);
  expect(panel!.y).toBeLessThan(360);
  const columns = await page
    .locator(".panel-content > .column")
    .evaluateAll((nodes) =>
      nodes.map((node) => node.getBoundingClientRect().x),
    );
  expect(new Set(columns).size).toBe(3);
  const toolbar = await page
    .getByRole("group", { name: "Course filters", exact: true })
    .locator("button")
    .evaluateAll((buttons) =>
      buttons.map((button) => Math.round(button.getBoundingClientRect().y)),
    );
  expect(new Set(toolbar).size).toBe(1);
  await page.locator(".filter-panel").screenshot({
    path: "/tmp/course-polish-details.png",
    animations: "disabled",
  });
});

test("dropdown keyboard selection survives a delayed distribution response", async ({
  page,
}) => {
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/facets?*", async (route) => {
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
  });
  const loaded = responseFor(page, "subject");
  await page.getByRole("button", { name: "Department", exact: true }).click();
  await page.keyboard.press("ArrowDown");
  const highlighted = page.locator(
    '.course-select-content [role="option"][data-highlighted]',
  );
  await expect(highlighted).toHaveCount(1);
  const id = await highlighted.getAttribute("id");
  const label = await highlighted.getAttribute("aria-label");
  const width = (await page.locator(".course-select-content").boundingBox())!
    .width;
  release();
  await body(await loaded);
  await expect(highlighted).toHaveAttribute("id", id!);
  await expect(highlighted).toHaveAttribute("aria-label", label!);
  expect(
    Math.abs(
      (await page.locator(".course-select-content").boundingBox())!.width -
        width,
    ),
  ).toBeLessThan(1);
  await page.keyboard.press("Enter");
  const code = label!.match(/\(([^)]+)\)$/)![1];
  await expect(page).toHaveURL(
    (url) => url.searchParams.get("subject") === code,
  );
});

test("panels resize without overflowing or detaching bars from their rows", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const loaded = responseFor(page, "level");
  await page
    .getByRole("button", { name: "Course details", exact: true })
    .click();
  await body(await loaded);
  for (const width of [1280, 860, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect
      .poll(async () =>
        chart(page, "Course numbers")
          .locator(".row-label")
          .evaluateAll((labels) =>
            labels.every((label) => label.scrollWidth <= label.clientWidth),
          ),
      )
      .toBe(true);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await expect
      .poll(async () =>
        page.locator(".facet-chart:not(.histogram)").evaluateAll((charts) =>
          charts.every((chart) => {
            const rows = [...chart.querySelectorAll(".chart-rows > button")];
            const bars = [
              ...chart.querySelectorAll('rect[fill="var(--muted)"]'),
            ];
            return (
              rows.length === bars.length &&
              rows.every((row, index) => {
                const bounds = row.getBoundingClientRect(),
                  bar = bars[index].getBoundingClientRect();
                return (
                  Math.abs(bounds.height - 36) < 1 &&
                  bar.y >= bounds.y - 1 &&
                  bar.bottom <= bounds.bottom + 1
                );
              })
            );
          }),
        ),
      )
      .toBe(true);
  }
  await page.locator(".filter-panel").screenshot({
    path: "/tmp/course-polish-narrow.png",
    animations: "disabled",
  });
  await page.keyboard.press("Escape");
  await expect(page.locator(".filter-panel")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Course details", exact: true }),
  ).toBeFocused();
  expect(errors).toEqual([]);
});

test("GPA and instructor panels stay compact and retain all choices", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const grades = responseFor(page, "gpa");
  await page.getByRole("button", { name: "Grades", exact: true }).click();
  await body(await grades);
  expect(
    (await page.locator(".filter-panel").boundingBox())!.height,
  ).toBeLessThan(330);
  await page.locator(".filter-panel").screenshot({
    path: "/tmp/course-polish-grades-dark.png",
    animations: "disabled",
  });
  const instructors = responseFor(page, "instructor");
  await page.getByRole("button", { name: "Instructor", exact: true }).click();
  const available = (await body(await instructors)).distributions.instructor
    .bins.length;
  await expect(
    chart(page, "Instructor").locator(".chart-rows > button"),
  ).toHaveCount(Math.min(6, available));
  if (available > 6) {
    await page
      .getByRole("button", { name: "Show more instructors", exact: true })
      .click();
    await expect(
      chart(page, "Instructor").locator(".chart-rows > button"),
    ).toHaveCount(available);
    await page
      .getByRole("button", { name: "Show fewer instructors", exact: true })
      .click();
  }
  expect(
    (await page.locator(".filter-panel").boundingBox())!.height,
  ).toBeLessThan(430);
});

test("distributions load on demand and reuse results only for the same search", async ({
  page,
}) => {
  let requests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/facets") requests++;
  });
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  expect(requests).toBe(0);
  const initial = responseFor(page, "level");
  const details = page.getByRole("button", {
    name: "Course details",
    exact: true,
  });
  await details.click();
  const original = (await body(await initial)).distributions.level.bins.find(
    (bin: any) => bin.value === "300",
  );
  const counts = chart(page, "Course numbers")
    .getByRole("button", { name: "300–399", exact: true })
    .locator(".facet-counts");
  const originalLabel = `${original.matched.toLocaleString()} matching / ${original.count.toLocaleString()} available courses`;
  await expect(counts).toHaveAttribute("aria-label", originalLabel);
  const schedule = responseFor(page, "days");
  await page.getByRole("button", { name: "Schedule", exact: true }).click();
  await body(await schedule);
  await expect(page.locator(".panel-content")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  const beforeReopen = requests;
  await details.click();
  await expect(counts).toHaveAttribute("aria-label", originalLabel);
  await expect(page.locator(".panel-content")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  expect(requests).toBe(beforeReopen);
  const changed = responseFor(page, "level", { credits_min: "3" });
  const input = page.getByRole("spinbutton", { name: "Credits at least" });
  await input.fill("3");
  const filtered = (await body(await changed)).distributions.level.bins.find(
    (bin: any) => bin.value === "300",
  );
  await expect(counts).toHaveAttribute(
    "aria-label",
    `${filtered.matched.toLocaleString()} matching / ${filtered.count.toLocaleString()} available courses`,
  );
  const beforeRestore = requests;
  await input.fill("");
  await expect(page).toHaveURL((url) => !url.searchParams.has("credits_min"));
  await expect(counts).toHaveAttribute("aria-label", originalLabel);
  await expect(page.locator(".panel-content")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  expect(requests).toBe(beforeRestore);
});

test("histogram tooltips expose matching and available counts to keyboard users", async ({
  page,
}) => {
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const loaded = responseFor(page, "gpa");
  await page.getByRole("button", { name: "Grades", exact: true }).click();
  const bin = (await body(await loaded)).distributions.gpa.bins.findLast(
    (bin: any) => bin.count > 0,
  );
  await chart(page, "Historical GPA")
    .getByRole("button", { name: `Historical GPA: ${bin.label}`, exact: true })
    .focus();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText(bin.label);
  await expect(tooltip).toContainText("Matching");
  await expect(tooltip).toContainText("Available");
  await expect(tooltip).toContainText(bin.count.toLocaleString());
});

test("bars interpolate between results and stop animating with reduced motion", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-10-01T12:00:00Z") });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.route("**/api/facets?*", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    const bins = Array.from({ length: 40 }, (_, index) => ({
      value: String(index / 10),
      label: `${(index / 10).toFixed(1)}–${((index + 1) / 10).toFixed(1)}`,
      count: (index + 1) * 10,
      matched:
        index / 10 >= Number(query.get("gpa_min") || 0) ? (index + 1) * 10 : 0,
    }));
    await route.fulfill({
      json: {
        revision: query.get("revision"),
        distributions: {
          gpa: {
            bins,
            total: bins.reduce((sum, bin) => sum + bin.count, 0),
            matched: bins.reduce((sum, bin) => sum + bin.matched, 0),
            missing: 0,
          },
        },
      },
    });
  });
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await page.getByRole("button", { name: "Grades", exact: true }).click();
  const selector = '.histogram rect[fill="var(--accent)"][data-value="2.5"]';
  const bar = page.locator(selector);
  await expect(bar).toHaveAttribute("height", "65");
  await page.clock.pauseAt(new Date("2026-10-01T12:01:00Z"));
  const sample = async (target: number) => {
    const heights: number[] = [];
    await expect
      .poll(
        async () => {
          await page.clock.runFor(40);
          const height = Number(await bar.getAttribute("height"));
          heights.push(height);
          return height;
        },
        { intervals: [10] },
      )
      .toBe(target);
    return heights;
  };
  const input = page.getByRole("spinbutton", {
    name: "Historical GPA at least",
  });
  await input.fill("3");
  const frames = await sample(0);
  expect(frames.some((height) => height > 0 && height < 65)).toBe(true);
  expect(
    frames.every((height, index) => index === 0 || height <= frames[index - 1]),
  ).toBe(true);
  await expect(bar).toHaveAttribute("height", "0");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await input.fill("");
  const reducedFrames = await sample(65);
  expect(reducedFrames.every((height) => height === 0 || height === 65)).toBe(
    true,
  );
  await expect(bar).toHaveAttribute("height", "65");
});

test("clicking GPA bins selects their exact interval, toggles off, and persists the top bin", async ({
  page,
}) => {
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const loaded = responseFor(page, "gpa");
  const grades = page.getByRole("button", { name: "Grades", exact: true });
  await grades.click();
  const original = (await body(await loaded)).distributions.gpa;
  const histogram = chart(page, "Historical GPA");
  const axis = await histogram.locator(".numeric-axis span").allTextContents();
  const bin = original.bins.find((bin: any) => bin.value === "3.5");
  const button = histogram.getByRole("button", {
    name: `Historical GPA: ${bin.label}`,
    exact: true,
  });
  const selected = responseFor(page, "gpa", {
    gpa_min: "3.5",
    gpa_max: "3.6",
    gpa_max_exclusive: "true",
  });
  await button.click();
  const after = (await body(await selected)).distributions.gpa;
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("spinbutton", { name: "Historical GPA at least" }),
  ).toHaveValue("3.5");
  await expect(
    page.getByRole("spinbutton", { name: "Historical GPA below" }),
  ).toHaveValue("3.6");
  expect(after.matched).toBe(bin.count);
  expect(
    after.bins
      .filter((bin: any) => bin.matched > 0)
      .map((bin: any) => bin.value),
  ).toEqual(["3.5"]);
  expect(after.bins.map((bin: any) => bin.count)).toEqual(
    original.bins.map((bin: any) => bin.count),
  );
  expect(
    await histogram.locator(".numeric-axis span").allTextContents(),
  ).toEqual(axis);
  await expect(page).toHaveURL(
    (url) => url.searchParams.get("gpa_max_exclusive") === "true",
  );
  const search = await page.request.get(
    `/api/search?${new URL(page.url()).searchParams}`,
  );
  expect((await search.json()).total).toBe(bin.count);
  await page.mouse.move(30, 100);
  await page.locator(".filter-panel").screenshot({
    path: "/tmp/course-gpa-bin-selected.png",
    animations: "disabled",
  });
  await button.focus();
  await page.keyboard.press("Enter");
  await expect(button).toHaveAttribute("aria-pressed", "false");
  await expect(page).toHaveURL(
    (url) =>
      !url.searchParams.has("gpa_min") &&
      !url.searchParams.has("gpa_max") &&
      !url.searchParams.has("gpa_max_exclusive"),
  );
  await expect(
    page.getByRole("spinbutton", { name: "Historical GPA at most" }),
  ).toHaveValue("");
  const top = original.bins.at(-1);
  const topButton = histogram.getByRole("button", {
    name: `Historical GPA: ${top.label}`,
    exact: true,
  });
  const topResponse = responseFor(page, "gpa", {
    gpa_min: "3.9",
    gpa_max: "4",
  });
  await topButton.focus();
  await page.keyboard.press("Space");
  expect((await body(await topResponse)).distributions.gpa.matched).toBe(
    top.count,
  );
  await expect(topButton).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("spinbutton", { name: "Historical GPA at most" }),
  ).toHaveValue("4");
  await expect(page).toHaveURL(
    (url) => !url.searchParams.has("gpa_max_exclusive"),
  );
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const restored = responseFor(page, "gpa");
  await grades.click();
  await body(await restored);
  await expect(topButton).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("spinbutton", { name: "Historical GPA at least" }),
  ).toHaveValue("3.9");
});

test("credit-bin selection stays coherent with numeric edits and works on a phone", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const loaded = responseFor(page, "credits");
  await page
    .getByRole("button", { name: "Course details", exact: true })
    .click();
  const original = (await body(await loaded)).distributions.credits;
  const histogram = chart(page, "Credits");
  const bin = original.bins.find((bin: any) => bin.value === "3");
  const button = histogram.getByRole("button", {
    name: `Credits: ${bin.label}`,
    exact: true,
  });
  const selected = responseFor(page, "credits", {
    credits_min: "3",
    credits_max: "3",
  });
  await button.click();
  expect((await body(await selected)).distributions.credits.matched).toBe(
    bin.count,
  );
  await expect(button).toHaveAttribute("aria-pressed", "true");
  const min = page.getByRole("spinbutton", { name: "Credits at least" });
  const max = page.getByRole("spinbutton", { name: "Credits at most" });
  await expect(min).toHaveValue("3");
  await expect(max).toHaveValue("3");
  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "false");
  await expect(page).toHaveURL(
    (url) =>
      !url.searchParams.has("credits_min") &&
      !url.searchParams.has("credits_max"),
  );
  await min.fill("3.5");
  const latest = responseFor(page, "credits", {
    credits_min: "4",
    credits_max: "4",
  });
  await histogram
    .getByRole("button", { name: "Credits: 4 credits", exact: true })
    .click();
  await body(await latest);
  await page.waitForTimeout(350);
  await expect(min).toHaveValue("4");
  await expect(max).toHaveValue("4");
  await expect(page).toHaveURL(
    (url) =>
      url.searchParams.get("credits_min") === "4" &&
      url.searchParams.get("credits_max") === "4",
  );
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("tags filter by the same course highlights, combine with AND, and update live counts", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const initial = responseFor(page, "tags");
  await page.getByRole("button", { name: "Tags", exact: true }).click();
  const before = (await body(await initial)).distributions.tags;
  const highlights = chart(page, "Course highlights");
  await expect(highlights.getByRole("button")).toHaveCount(5);
  await expect(page.locator(".tag-definitions")).toContainText(
    "Median enrollment of 30 or fewer",
  );
  await expect(page.locator(".tag-definitions")).toContainText(
    "the selected department",
  );
  const picked = responseFor(page, "tags", { tags: "small-lectures" });
  const small = highlights.getByRole("button", {
    name: "Small lectures",
    exact: true,
  });
  await small.click();
  const afterSmall = (await body(await picked)).distributions.tags;
  expect(afterSmall.matched).toBe(
    before.bins.find((bin: any) => bin.value === "small-lectures").count,
  );
  await expect(small).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.locator(".discovery-card").first().locator(".evidence-badge").first(),
  ).toHaveText("Small lectures");
  const combined = responseFor(page, "tags", {
    tags: "small-lectures,higher-grades",
  });
  const higher = highlights.getByRole("button", {
    name: "Higher grades",
    exact: true,
  });
  await higher.focus();
  await page.keyboard.press("Enter");
  const afterBoth = (await body(await combined)).distributions.tags;
  expect(afterBoth.matched).toBeLessThan(afterSmall.matched);
  expect(afterBoth.matched).toBeGreaterThan(0);
  expect(afterBoth.bins.map((bin: any) => [bin.value, bin.count])).toEqual(
    before.bins.map((bin: any) => [bin.value, bin.count]),
  );
  await expect(higher).toBeFocused();
  await expect(higher).toHaveAttribute("aria-pressed", "true");
  const results = await page.request.get(
    `/api/search?${new URL(page.url()).searchParams}`,
  );
  const selected = await results.json();
  expect(selected.total).toBe(afterBoth.matched);
  expect(
    selected.items.every((item: any) =>
      ["small-lectures", "higher-grades"].every((tag) =>
        item.badges.some((badge: any) => badge.tag === tag),
      ),
    ),
  ).toBe(true);
  await expect(page.locator(".panel-content")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  const toolbarRows = await page
    .getByRole("group", { name: "Course filters", exact: true })
    .locator("button")
    .evaluateAll((buttons) =>
      buttons.map((button) => Math.round(button.getBoundingClientRect().y)),
    );
  expect(new Set(toolbarRows).size).toBe(1);
  expect(
    (await page.locator(".filter-panel").boundingBox())!.height,
  ).toBeLessThan(400);
  await page.screenshot({
    path: "/tmp/course-tags-desktop.png",
    animations: "disabled",
  });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await page.getByRole("button", { name: "Tags", exact: true }).click();
  await expect(
    chart(page, "Course highlights").getByRole("button", {
      name: "Small lectures",
      exact: true,
    }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    chart(page, "Course highlights").getByRole("button", {
      name: "Higher grades",
      exact: true,
    }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Tags", exact: true }),
  ).toBeFocused();
  expect(errors).toEqual([]);
});

test("tag filters fit narrow screens and allow removing a tag without clearing context", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(
    "/search?subject=COMPSCI&availability=all&tags=small-lectures",
  );
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const loaded = responseFor(page, "tags");
  await page.getByRole("button", { name: "Tags", exact: true }).click();
  await body(await loaded);
  await page.screenshot({
    path: "/tmp/course-tags-mobile.png",
    animations: "disabled",
  });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await expect(
      chart(page, "Course highlights").getByRole("button", {
        name: "Highly rated instructor",
        exact: true,
      }),
    ).toBeVisible();
  }
  const removed = responseFor(page, "tags");
  await chart(page, "Course highlights")
    .getByRole("button", { name: "Small lectures", exact: true })
    .click();
  await body(await removed);
  await expect(page).toHaveURL(
    (url) =>
      !url.searchParams.has("tags") &&
      url.searchParams.get("subject") === "COMPSCI" &&
      url.searchParams.get("availability") === "all",
  );
});

test("department alternatives honor the grade tag’s own comparison group", async ({
  page,
}) => {
  await page.goto("/search?subject=MATH&availability=all&tags=higher-grades");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const loaded = responseFor(page, "subject");
  await page.getByRole("button", { name: "Department", exact: true }).click();
  const departments = (await body(await loaded)).distributions.subject;
  const count = departments.bins.find(
    (bin: any) => bin.value === "COMPSCI",
  ).count;
  await page
    .getByRole("option", { name: "Computer Sciences (COMPSCI)", exact: true })
    .click();
  await expect(page).toHaveURL(
    (url) =>
      url.searchParams.get("subject") === "COMPSCI" &&
      url.searchParams.get("tags") === "higher-grades",
  );
  const response = await page.request.get(
    `/api/search?${new URL(page.url()).searchParams}`,
  );
  expect((await response.json()).total).toBe(count);
  await expect(page.locator(".finder > .results-heading")).toContainText(
    String(count),
  );
});
