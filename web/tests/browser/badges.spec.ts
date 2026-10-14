import { expect, test } from "@playwright/test";
import { DatabaseSync } from "node:sqlite";
import { courseUrl, termName } from "../../../src/lib/format";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const {
  tagThresholds,
  ratingPriorWeight,
} = require("../../../src/lib/search-policy.json");
const {
  names: departmentNames,
} = require("../../../src/lib/data/department-names.json");

// Select records with the evidence this interaction needs from the CI import.
// Names, terms, ratings and model provenance belong to the data release.
function fixtures() {
  const db = new DatabaseSync(".site/import/site.sqlite", { readOnly: true });
  try {
    const prior = db
      .prepare(
        "SELECT AVG(json_extract(payload,'$.quality_rating')) mean FROM reviews WHERE json_extract(payload,'$.quality_rating') BETWEEN 1 AND 5",
      )
      .get() as { mean: number };
    const rows = db
      .prepare(
        `
      SELECT c.payload course, i.payload instructor FROM courses c
      JOIN json_each(c.payload,'$.instructors') roster
      JOIN instructors i ON i.uid=json_extract(roster.value,'$.instructor_uid')
      WHERE EXISTS (SELECT 1 FROM grade_summaries g WHERE g.uid=c.uid)
      AND json_extract(i.payload,'$.ratings.quality_count') >= ?
      ORDER BY c.uid,i.uid
    `,
      )
      .all(tagThresholds.qualityRatings) as {
      course: string;
      instructor: string;
    }[];
    const rated = rows
      .map((row) => ({
        course: JSON.parse(row.course),
        teacher: JSON.parse(row.instructor),
      }))
      .find(
        ({ teacher }) =>
          (teacher.ratings.quality * teacher.ratings.quality_count +
            prior.mean * ratingPriorWeight) /
            (teacher.ratings.quality_count + ratingPriorWeight) >=
          tagThresholds.quality,
      );
    if (!rated)
      throw new Error(
        "Imported dataset needs a current highly rated instructor and course grade history",
      );
    const enriched = db
      .prepare(
        `SELECT payload FROM courses
      WHERE json_extract(payload,'$.llm_model') IS NOT NULL
      AND json_extract(payload,'$.llm_model_revision') IS NOT NULL
      AND length(json_extract(payload,'$.llm_summary')) > 0
      AND json_array_length(payload,'$.llm_assumed_background') > 0
      ORDER BY uid LIMIT 1`,
      )
      .get() as { payload: string } | undefined;
    if (!enriched)
      throw new Error(
        "Imported dataset needs an enriched course with recorded model provenance",
      );
    return { ...rated, enriched: JSON.parse(enriched.payload) };
  } finally {
    db.close();
  }
}
const fixture = fixtures();

test("course badges explain scope and respond to term and comparison changes", async ({
  page,
}) => {
  await page.goto(courseUrl(fixture.course.course_id));
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const header = page.locator(".course-identity");
  await expect(
    header.getByRole("button", {
      name: "Highly rated instructor",
      exact: true,
    }),
  ).toBeVisible();
  await header
    .getByRole("button", { name: "Highly rated instructor", exact: true })
    .hover();
  const evidence = page.getByRole("dialog", {
    name: "Highly rated instructor evidence",
  });
  await expect(evidence).toContainText(fixture.teacher.name);
  await expect(evidence).toContainText(termName(fixture.course.semester));
  expect(
    await header
      .getByRole("button", { name: "Highly rated instructor", exact: true })
      .evaluate((e) => e.matches(":focus-visible")),
  ).toBe(false);
  await page.keyboard.press("Escape");
  await expect(evidence).toHaveCount(0);
  const initialGrades = header
    .locator(".evidence-badge")
    .filter({ hasText: /Higher grades|Lower grades/ });
  if (await initialGrades.count()) {
    await initialGrades.focus();
    const latest = fixture.course.grades
      .map((g: { term_id: string }) => g.term_id)
      .filter((t: string) => t <= fixture.course.semester)
      .sort()
      .at(-1);
    await expect(page.locator(".badge-evidence")).toContainText(
      termName(latest),
    );
    await page.keyboard.press("Escape");
    await expect(page.locator(".badge-evidence")).toHaveCount(0);
  }
  await page
    .getByRole("button", { name: "Comparison group", exact: true })
    .click();
  await page
    .getByRole("option", {
      name: `Department · ${fixture.course.subjects[0]}`,
      exact: true,
    })
    .click();
  const grades = header
    .locator(".evidence-badge")
    .filter({ hasText: /Higher grades|Lower grades/ });
  if (await grades.count()) {
    await grades.press("Tab");
    await grades.focus();
    await expect(page.locator(".badge-evidence")).toContainText(
      departmentNames[fixture.course.subjects[0]] || fixture.course.subjects[0],
    );
    await page.keyboard.press("Escape");
  }
  await page.getByRole("button", { name: "Term", exact: true }).click();
  await page
    .getByRole("option", { name: "All recorded terms", exact: true })
    .click();
  await page.keyboard.press("Tab");
  await header
    .getByRole("button", { name: "Highly rated instructor", exact: true })
    .focus();
  await expect(page.locator(".badge-evidence")).toContainText(
    termName(fixture.course.semester),
  );
});

test("profiles and discovery lists share badges without nesting buttons in links", async ({
  page,
}) => {
  await page.goto(courseUrl(fixture.course.course_id));
  const profile = await page
    .locator(".current-teachers")
    .getByRole("link", {
      name: new RegExp(
        fixture.teacher.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
      ),
    })
    .getAttribute("href");
  expect(profile).toBeTruthy();
  for (const route of [
    profile!,
    "/instructors/by-rating-count",
    "/search?q=" + encodeURIComponent(fixture.course.course_id),
    "/departments/" + encodeURIComponent(fixture.course.subjects[0]),
  ]) {
    await page.goto(route);
    await expect(page.locator(".evidence-badge").first()).toBeVisible();
    await expect(page.locator("a .evidence-badge")).toHaveCount(0);
    expect(
      await page
        .locator(
          ".discovery-card .student-badges, .instructor-result .student-badges",
        )
        .evaluateAll((rows) => rows.every((row) => row.children.length <= 2)),
    ).toBe(true);
  }
});

test("badge evidence opens on touch and fits mobile and dark layouts", async ({
  browser,
  baseURL,
}) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  await page.goto(new URL(courseUrl(fixture.course.course_id), baseURL).href);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await page
    .locator(".course-identity")
    .getByRole("button", { name: "Highly rated instructor", exact: true })
    .tap();
  const evidence = page.getByRole("dialog", {
    name: "Highly rated instructor evidence",
  });
  await expect(evidence).toBeVisible();
  await expect
    .poll(() =>
      evidence.evaluate((e) => {
        const r = e.getBoundingClientRect();
        return r.left >= 0 && r.right <= innerWidth;
      }),
    )
    .toBe(true);
  await page.getByRole("button", { name: "Close badge evidence" }).tap();
  await expect(evidence).toHaveCount(0);
  await page
    .getByRole("button", { name: "Color theme: system. Switch to light" })
    .click();
  await page
    .getByRole("button", { name: "Color theme: light. Switch to dark" })
    .click();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "test-results/badges-mobile-dark.png" });
  await context.close();
});

test("all AI disclaimers share HF publisher attribution", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  let requests = 0;
  const model = fixture.enriched.llm_model;
  const revision = fixture.enriched.llm_model_revision;
  const owner = model.split("/")[0].toLowerCase();
  const avatar = `https://cdn-avatars.huggingface.co/test-${owner}.svg`;
  await page.route(
    `https://huggingface.co/api/organizations/${owner}/overview`,
    (route) => {
      requests++;
      return route.fulfill({ json: { fullname: owner, avatarUrl: avatar } });
    },
  );
  await page.route(avatar, (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><circle cx="10" cy="10" r="8" fill="green"/></svg>',
    }),
  );
  await page.goto(courseUrl(fixture.enriched.course_id));
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  expect(requests).toBe(0);
  const labels = await page
    .locator(".ai-disclaimer:visible")
    .evaluateAll((elements) =>
      elements.map((e) => e.getAttribute("aria-label")!),
    );
  expect(labels.length).toBeGreaterThanOrEqual(2);
  for (const label of labels) {
    const trigger = page.getByRole("button", { name: label, exact: true });
    const tooltip = page.getByRole("tooltip").filter({ hasText: model });
    await trigger.scrollIntoViewIfNeeded();
    // Tooltips dismiss on scroll. A pending automatic scroll can close one
    // after its first visibility check, so retry the complete interaction.
    await expect(async () => {
      await trigger.click();
      await expect(tooltip).toBeVisible({ timeout: 500 });
      await expect(tooltip).toContainText(revision, { timeout: 500 });
      await expect(tooltip.getByRole("img", { name: owner })).toBeVisible({
        timeout: 500,
      });
    }).toPass({ timeout: 5000 });
    await page.keyboard.press("Escape");
    await expect(tooltip).toHaveCount(0);
  }
  expect(requests).toBe(1);
});
