import { test, expect, type Locator } from "@playwright/test";
import { readFile } from "node:fs/promises";
import {
  currentCourse,
  currentPath,
  importedCourse,
  importedAsset,
  latestGradeTerm,
} from "./dataset";
import { courseUrl, courseTitle, termName } from "../../../src/lib/format";
import {
  sectionName,
  monday,
  localTime,
  addDays,
  dayLabel,
} from "../../../src/lib/calendar";
const numberValues = (locator: Locator) =>
  locator
    .getByRole("img")
    .evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("aria-label")),
    );
const uid = "course_28c3390ba944d49fd17f7c72";
test("course reading, citations, graph and theme", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(currentPath);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await expect(
    page.getByRole("heading", {
      name: courseTitle(currentCourse.title),
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.locator(".catalog-description p")).toHaveText(
    currentCourse.description,
  );
  await page.locator("#requirements").scrollIntoViewIfNeeded();
  await expect(
    page.getByText("Prerequisite text tree", { exact: true }),
  ).toBeVisible();
  if (currentCourse.requirements.nodes.some((n: any) => n.kind === "course"))
    await expect(
      page.getByRole("region", { name: "Prerequisite relationships" }),
    ).toBeVisible();
  await page
    .getByRole("button", { name: "Color theme: system. Switch to light" })
    .click();
  await page
    .getByRole("button", { name: "Color theme: light. Switch to dark" })
    .click();
  await expect(page.locator("html")).toHaveClass("dark");
  const technical = page.locator(".technical-sources");
  await technical.locator(":scope > summary").click();
  const traces = technical
    .locator("details")
    .filter({ has: page.getByText("Full model traces", { exact: true }) });
  await traces.locator(":scope > summary").click();
  await expect(traces.getByRole("link")).toHaveCount(
    currentCourse.evidence.traces.length,
  );
  expect(errors).toEqual([]);
});

test("search resolves aliases and exposes filters", async ({ page }) => {
  await page.goto("/search?q=CS300");
  const result = await (await page.request.get("/api/search?q=CS300")).json();
  await expect(
    page.locator(".discovery-card .course-description").first(),
  ).toHaveText(result.items[0].description);
  await expect(page.locator(".discovery-card").first()).toContainText(
    "COMPSCI 300",
  );
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await page.getByLabel("Search courses", { exact: true }).fill("programming");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.locator(".discovery-card").first()).toBeVisible();
});
test("mobile layout stays within viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/courses/COMPSCI_300");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: "test-results/cs300-mobile.png",
    fullPage: true,
  });
});
test("course content is available without JavaScript", async ({
  browser,
  baseURL,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto(new URL("/courses/COMPSCI_300", baseURL).href);
  await expect(
    page.getByRole("heading", { name: "Programming II", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Prerequisite text tree", { exact: true }),
  ).toBeVisible();
  await context.close();
});

test("grade filters reset and instructor links retain course context", async ({
  page,
}) => {
  await page.goto("/courses/COMPSCI_300");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const grades = page.locator("#grades");
  const count = grades.locator(".metric-strip");
  const overall = await numberValues(count);
  const instructors = grades.getByRole("button", {
    name: "Instructor",
    exact: true,
  });
  await instructors.click();
  const option = page.getByRole("listbox").getByRole("option").nth(1);
  const response = page.waitForResponse(
    (r) => r.url().includes(`/api/courses/${uid}/grades`) && r.ok(),
  );
  await option.click();
  await response;
  await expect(grades.getByText("Loading grades…")).not.toBeVisible();
  await instructors.click();
  await page
    .getByRole("option", { name: "Course overall", exact: true })
    .click();
  await expect.poll(() => numberValues(count)).toEqual(overall);
  const professor = page.locator("#professors h3 a").first();
  const name = await professor.textContent();
  await professor.click();
  await expect(
    page.getByRole("heading", { name: name!, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Recorded teaching history" }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/instructor.png",
    fullPage: true,
  });
});

test("home and cross-listed course render on desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(
    page.getByRole("region", { name: "Campus activity" }),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/home.png", fullPage: true });
  await page.goto("/courses/cs-759");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await expect(page.locator("h1")).toContainText("High Performance Computing");
  await page.locator("#grades").scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/cs759.png", fullPage: true });
});

test("calendar filters meetings, exposes details and exports dates", async ({
  page,
}) => {
  const meetings = currentCourse.evidence.meetings
    .flatMap((path: string) => importedAsset(path))
    .filter((m: any) => m.meeting_type === "CLASS");
  const sections = [
    ...new Set<string>(
      meetings
        .map((m: any) => sectionName(m.name))
        .filter((name: string) => name.startsWith("LEC ")),
    ),
  ].sort();
  expect(sections.length).toBeGreaterThan(1);
  const selected = meetings
    .filter((m: any) => sectionName(m.name) === sections[0])
    .sort((a: any, b: any) => a.starts_at.localeCompare(b.starts_at));
  await page.goto(currentPath);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const schedule = page.locator("#schedule");
  await schedule.locator(".course-calendar").scrollIntoViewIfNeeded();
  await expect(schedule.locator(".week-grid")).toBeVisible();
  await page
    .getByRole("button", { name: "Calendar section", exact: true })
    .click();
  await page.getByRole("option", { name: sections[0], exact: true }).click();
  await expect(schedule.locator(".meeting").first()).toContainText(sections[0]);
  await expect(
    schedule.locator(".meeting").filter({ hasText: sections[1] }),
  ).toHaveCount(0);
  await schedule.locator(".meeting").first().click();
  await expect(
    page.getByRole("dialog", { name: "Meeting details" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Open in Google Maps" }),
  ).toHaveAttribute("href", /google\.com\/maps\/search/);
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("dialog", { name: "Meeting details" }),
  ).toHaveCount(0);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("course-schedule.ics");
  const exported = await readFile((await file.path())!, "utf8");
  expect(exported).toContain("BEGIN:VCALENDAR");
  expect(exported).toContain(
    `SUMMARY:${currentCourse.course_id} · ${sections[0]}`,
  );
  expect(exported).not.toContain(
    `SUMMARY:${currentCourse.course_id} · ${sections[1]}`,
  );
  for (const meeting of selected) {
    const stamp = new Date(meeting.starts_at.replace(" ", "T"))
      .toISOString()
      .replace(/[-:]/g, "")
      .replace(".000", "");
    expect(exported).toContain(`DTSTART:${stamp}`);
  }
  const beforeWeek = await schedule.locator(".week-label").textContent();
  await page.getByRole("button", { name: "Next week" }).click();
  await expect(schedule.locator(".week-label")).not.toHaveText(beforeWeek!);
  await expect(page.getByRole("tab")).toHaveCount(0);
  await page.screenshot({ path: "test-results/calendar-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(schedule.locator(".agenda")).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await schedule.locator(".agenda button").first().click();
  const meetingCard = page.getByRole("dialog", { name: "Meeting details" });
  await expect(meetingCard).toBeVisible();
  await expect
    .poll(() =>
      meetingCard.evaluate((el) => {
        const r = el.getBoundingClientRect();
        return r.left >= 0 && r.right <= innerWidth;
      }),
    )
    .toBe(true);
  await page.getByRole("button", { name: "Close meeting details" }).click();
  await expect(meetingCard).toHaveCount(0);
  await page.screenshot({ path: "test-results/calendar-mobile.png" });
});

test("course context, projection and captured instructor ratings remain distinct", async ({
  page,
}) => {
  await page.goto(currentPath);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const document = await (await page.request.get(currentPath + ".json")).json();
  await expect(
    page.getByRole("button", { name: "Term", exact: true }),
  ).toContainText(termName(document.data.course.semester));
  await expect(page.locator("#grades .grade-estimate")).toHaveCount(
    document.data.projection?.interval ? 1 : 0,
  );
  await expect(page.locator(".projection")).toHaveCount(0);
  const teacher = document.data.course.instructors.find(
    (i: any) => i.ratings?.quality_count >= 10,
  );
  expect(teacher).toBeDefined();
  const tile = page
    .locator("#professors article")
    .filter({ hasText: teacher.name });
  await expect(tile.locator(".rating-values")).toContainText("Adjusted rating");
  await expect(
    tile.locator(".rating-values").getByRole("img", {
      name: String(teacher.ratings.review_count),
      exact: true,
    }),
  ).toBeVisible();
  await tile.getByRole("link", { name: teacher.name, exact: true }).click();
  await expect(
    page.getByRole("heading", { name: teacher.name, exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".rating-values").getByRole("img", {
      name: String(teacher.ratings.review_count),
      exact: true,
    }),
  ).toBeVisible();
});

test("takeaways rotate and pause for reading sources", async ({ page }) => {
  await page.clock.install();
  await page.goto(currentPath);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const card = page.getByRole("region", {
    name: "Student takeaways",
    exact: true,
  });
  const content = card.locator(".takeaway:visible");
  const initial = await content.textContent();
  await page.mouse.move(0, 0);
  await page.clock.fastForward(8000);
  await expect(content).not.toHaveText(initial!);
  await card.getByRole("button", { name: "Pause takeaway rotation" }).click();
  const paused = await content.textContent();
  await page.mouse.move(0, 0);
  await page.clock.fastForward(16000);
  await expect(content).toHaveText(paused!);
  await card.getByRole("button", { name: "Next takeaway" }).click();
  await expect(content).not.toHaveText(paused!);
  await expect(
    card.getByRole("button", { name: "Resume takeaway rotation" }),
  ).toBeVisible();
});

test("school and department comparisons stay synchronized", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/courses/COMPSCI_300");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await page.getByRole("button", { name: "Term", exact: true }).click();
  await page.getByRole("option", { name: "Spring 2026", exact: true }).click();
  const metrics = page.locator("#grades .metric-strip");
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  const trigger = metrics.getByRole("button", {
    name: "Average GPA comparison",
    exact: true,
  });
  await trigger.hover();
  await expect(page.getByRole("tooltip")).toBeVisible();
  const school = await numberValues(page.getByRole("tooltip"));
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Comparison group", exact: true })
    .click();
  await page
    .getByRole("option", { name: "Department · COMPSCI", exact: true })
    .click();
  await trigger.focus();
  await expect(page.getByRole("tooltip")).toContainText("COMPSCI");
  await expect
    .poll(() => numberValues(page.getByRole("tooltip")))
    .not.toEqual(school);
  await page.keyboard.press("Escape");
  await expect(page.locator(".course-context .context-heading")).toContainText(
    "COMPSCI",
  );
  await expect(metrics.locator(".metric-tooltip-trigger")).toHaveCount(3);
  await page.getByRole("button", { name: "Term", exact: true }).click();
  await page.getByRole("option", { name: "Spring 2026", exact: true }).click();
  await expect(
    metrics.getByRole("img", { name: "478", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Comparison group", exact: true })
    .click();
  await page.keyboard.press("Home");
  await page.keyboard.press("Enter");
  await expect(page.locator(".course-context .context-heading")).toContainText(
    "UW–Madison",
  );
});

test("animated numbers preserve accessible values with reduced motion", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/courses/COMPSCI_300");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const metrics = page.locator("#grades .metric-strip");
  await expect(
    page
      .locator(".grade-snapshot")
      .getByRole("img", { name: "11,038", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Term", exact: true }).click();
  await page.getByRole("option", { name: "Spring 2026", exact: true }).click();
  await expect(
    metrics.getByRole("img", { name: "478", exact: true }),
  ).toBeVisible();
  expect(
    await metrics
      .locator("number-flow-svelte")
      .evaluateAll((nodes) =>
        nodes.every(
          (node) =>
            !node.shadowRoot
              ?.getAnimations()
              .some((animation) => animation.playState === "running"),
        ),
      ),
  ).toBe(true);
});

test("metric comparison details open on touch", async ({
  browser,
  baseURL,
}) => {
  const context = await browser.newContext({
    hasTouch: true,
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  await page.goto(new URL("/courses/COMPSCI_300", baseURL).href);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await page
    .locator(".grade-snapshot")
    .getByRole("button", { name: "Average GPA comparison" })
    .tap();
  await expect(page.getByRole("tooltip")).toContainText("UW–Madison");
  await page.locator("h1").tap();
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await context.close();
});

test("inline citations show original comments without expanding the page", async ({
  page,
}) => {
  const summarized = importedCourse(
    "json_array_length(payload,'$.student_summary.quick_take') > 0",
    false,
  );
  const course = summarized || currentCourse;
  await page.goto(courseUrl(course.course_id));
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const trigger = page.locator("#overview [data-citation-trigger]").first();
  if (!summarized) {
    // Source-first releases retain comments while current-term generations are pending.
    await expect(page.locator("#overview [data-citation-trigger]")).toHaveCount(
      0,
    );
    const reviews = page.getByRole("region", { name: "Review sources" });
    await reviews.getByText("Read original reviews", { exact: true }).click();
    const source = importedAsset(course.evidence.reviews[0]).find(
      (r: any) => r.comment,
    );
    expect(source).toBeDefined();
    await reviews.locator("details details > summary").first().click();
    await expect(reviews.locator("blockquote").first()).toHaveText(
      source.comment,
    );
    return;
  }
  const before = await page.locator("#overview").boundingBox();
  await trigger.click();
  const sources = page.getByRole("dialog", { name: "Sources", exact: true });
  await expect(sources.locator("blockquote").first()).toBeVisible();
  await expect(sources).toContainText("Rate My Professors");
  await expect(
    sources.getByRole("link", { name: "View RMP profile" }).first(),
  ).toHaveAttribute("href", /^https:\/\/www.ratemyprofessors.com\/professor\//);
  expect((await page.locator("#overview").boundingBox())?.height).toBe(
    before?.height,
  );
  await expect(sources.locator("pre")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(sources).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("grade history fits curved instructor lines and identifies them on hover", async ({
  page,
}) => {
  await page.goto("/courses/COMPSCI_300");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const chart = page.locator("#grades .charts > div").last();
  const paths = chart.locator("path.lc-path");
  expect(
    await paths.evaluateAll(
      (nodes) =>
        nodes.filter((node) => node.getAttribute("d")?.includes("C")).length,
    ),
  ).toBeGreaterThan(4);
  await expect(chart.locator(".trend-legend")).toHaveCount(0);
  await chart.locator(".chart").hover();
  await expect(page.locator(".lc-tooltip-root")).toContainText(
    "Course average",
  );
  await expect(page.locator(".lc-tooltip-root")).not.toContainText("total");
  await chart.screenshot({
    path: "/tmp/uwcourses-design-audit/all-instructor-trends.png",
  });
});

test("term selection updates context, roster, history and snapshot availability", async ({
  page,
}) => {
  await page.goto(currentPath);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const term = page.getByRole("button", { name: "Term", exact: true });
  const current = termName(currentCourse.semester),
    past = termName(latestGradeTerm);
  await expect(term).toContainText(current);
  const document = await (await page.request.get(currentPath + ".json")).json();
  const rosterCount = await page.locator("#professors .professor-tile").count();
  await expect(
    page.locator('.current-teachers a[href^="/instructors/"]'),
  ).toHaveCount(Math.min(rosterCount, 3));
  const snapshot = await numberValues(page.locator(".grade-snapshot"));
  await term.click();
  await page.getByRole("option", { name: past, exact: true }).click();
  await expect(page.locator(".course-context")).toContainText(past);
  await expect(page.locator("#professors .panel-heading")).toContainText(past);
  expect(await numberValues(page.locator(".grade-snapshot"))).toEqual(snapshot);
  await expect(page.locator("#experience")).toContainText(
    `No student-experience summary for ${past}`,
  );
  await expect(page.locator("#requirements")).toContainText(
    `No prerequisite snapshot for ${past}`,
  );
  await expect(page.locator("#schedule")).toContainText(
    `No calendar captured for ${past}`,
  );
  await expect(page.locator("#schedule tbody tr")).toHaveCount(0);
  await expect(page.locator("#grades .grade-estimate")).toHaveCount(0);
  await expect(page.locator("#grades .trend-heading p")).toHaveText(
    `Through ${past}`,
  );
  await term.click();
  await page
    .getByRole("option", {
      name:
        current + (document.data.projection?.interval ? " · Projected" : ""),
      exact: true,
    })
    .click();
  for (const teacher of document.data.course.instructors)
    await expect(page.locator("#professors")).toContainText(teacher.name);
  await expect(page.locator("#grades .grade-estimate")).toHaveCount(
    document.data.projection?.interval ? 1 : 0,
  );
  await expect(page.locator("#schedule tbody tr").first()).toBeVisible();
});

test("historical instructors without a recorded name do not break course pages", async ({
  page,
}) => {
  const response = await page.goto("/courses/african-203");
  expect(response?.status()).toBe(200);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await page.getByRole("button", { name: "Term", exact: true }).click();
  await page
    .getByRole("option", { name: "All recorded terms", exact: true })
    .click();
  await expect(page.locator("#professors")).toContainText("Unknown instructor");
});

test("insufficient projection history falls back only inside grades", async ({
  page,
}) => {
  const course = importedCourse(
    `(SELECT count(*) FROM grade_summaries g WHERE g.uid=c.uid) BETWEEN 1 AND 2 AND NOT EXISTS(SELECT 1 FROM grade_summaries g WHERE g.uid=c.uid AND g.term=json_extract(c.payload,'$.semester'))`,
  );
  const latest = course.grades
    .map((g: any) => g.term_id)
    .sort()
    .at(-1);
  await page.goto(courseUrl(course.course_id));
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await expect(
    page.getByRole("button", { name: "Term", exact: true }),
  ).toHaveText(termName(course.semester));
  await expect(page.locator("#grades .fallback-note")).toContainText(
    `Latest available · ${termName(latest)}`,
  );
  await expect(page.locator("#grades .grade-estimate")).toHaveCount(0);
  await expect(page.locator("#grades .metric-strip")).toBeVisible();
  await expect(page.locator("#professors .panel-heading")).toContainText(
    termName(course.semester),
  );
  await page.getByRole("button", { name: "Term", exact: true }).click();
  await page
    .getByRole("option", { name: termName(latest), exact: true })
    .click();
  await expect(page.locator("#grades .fallback-note")).toHaveCount(0);
  await expect(page.locator("#grades .grade-percentages")).toBeVisible();
});

test("calculated grade and enrollment observations rotate with official learning outcomes", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(currentPath);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const card = page.getByRole("region", {
    name: "Student takeaways",
    exact: true,
  });
  const count = Number(
    (await card.locator(".controls span").textContent())!.split("/")[1],
  );
  let gradeSeen = false,
    learningSeen = false;
  for (let i = 0; i < count; i++) {
    if (await card.locator(".observation-source:visible").count()) {
      const source = await card
        .locator(".observation-source:visible")
        .textContent();
      if (source?.includes("Recorded grades")) {
        gradeSeen = true;
        await expect(card.locator(".claim")).toContainText("UW–Madison");
        await expect(card.locator("[data-citation-trigger]")).toHaveCount(0);
      }
      if (source?.includes("Section enrollment")) {
        expect(currentCourse.sections.some((s: any) => s.enrolled > 0)).toBe(
          true,
        );
        await expect(card.locator(".observation-source")).toContainText(
          termName(currentCourse.semester),
        );
      }
    }
    if (
      await card
        .getByRole("region", { name: "Official learning outcomes" })
        .count()
    ) {
      learningSeen = true;
      await expect(card.locator(".learning-slide:visible")).toContainText(
        currentCourse.official_learning_outcomes[0].text,
      );
    }
    await card.getByRole("button", { name: "Next takeaway" }).click();
  }
  expect(gradeSeen).toBe(true);
  expect(learningSeen).toBe(true);
});

test("course-fit charts remain visible for unreleased terms and heading comparison stays synchronized", async ({
  page,
}) => {
  await page.goto("/courses/COMPSCI_300");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const context = page.locator(".course-context");
  await expect(context.locator("h2")).toContainText(
    "Where this course fits relative to UW–Madison",
  );
  await expect(context.locator(".context-heading")).toContainText(
    "Latest available grades",
  );
  await expect(
    context.locator('.context-chart svg[role="figure"]').first(),
  ).toBeVisible();
  await expect(
    context.locator('.scale-comparison svg[role="figure"]').first(),
  ).toBeVisible();
  await context
    .getByRole("button", { name: "Course fit comparison", exact: true })
    .click();
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Comparison group", exact: true }),
  ).toContainText("COMPSCI");
  await expect(context.locator("h2")).toContainText("COMPSCI");
  await expect(
    context.locator('.context-chart svg[role="figure"]').first(),
  ).toBeVisible();
  await context
    .getByRole("button", { name: "Course fit comparison", exact: true })
    .press("Enter");
  await expect(
    page.getByRole("button", { name: "Comparison group", exact: true }),
  ).toContainText("UW–Madison");
  await context
    .getByRole("button", { name: "Course fit comparison", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Comparison group", exact: true })
    .click();
  await page
    .getByRole("option", { name: "School · UW–Madison", exact: true })
    .click();
  await expect(
    context.getByRole("button", { name: "Course fit comparison", exact: true }),
  ).toContainText("UW–Madison");
  await context.screenshot({
    path: "/tmp/uwcourses-design-audit/course-fit-comparison.png",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("Bayesian instructor ratings show their source and sort the course roster consistently", async ({
  page,
}) => {
  await page.goto(currentPath);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const document = await (await page.request.get(currentPath + ".json")).json();
  const teacher = document.data.course.instructors.find(
    (i: any) => i.ratings?.quality_count >= 10,
  );
  expect(teacher).toBeDefined();
  const scores = await page
    .locator(".current-teachers .teacher-rating")
    .evaluateAll((nodes) =>
      nodes.map((node) => Number(node.textContent?.split("/")[0])),
    );
  expect(scores).toEqual([...scores].sort((a, b) => b - a));
  const tile = page
    .locator("#professors article")
    .filter({ hasText: teacher.name });
  const adjusted = `${teacher.ratings.bayesian_quality.toFixed(1)}/5`;
  await expect(tile.locator(".rating-values")).toContainText("Adjusted rating");
  await expect(
    tile
      .locator(".rating-values")
      .getByRole("img", { name: adjusted, exact: true }),
  ).toBeVisible();
  await tile.getByText("About this rating", { exact: true }).click();
  await expect(tile.locator(".rating-method")).toContainText(
    `Raw average: ${teacher.ratings.quality}/5 from ${teacher.ratings.quality_count} quality ratings`,
  );
  await expect(tile.locator(".rating-method")).toContainText(
    `${teacher.ratings.prior_weight} additional ratings`,
  );
  await tile.getByRole("link", { name: teacher.name, exact: true }).click();
  await expect(
    page
      .locator(".rating-values")
      .getByRole("img", { name: adjusted, exact: true }),
  ).toBeVisible();
});
