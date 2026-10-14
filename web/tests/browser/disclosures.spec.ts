import { expect, test } from "@playwright/test";
import { importedCourse } from "./dataset";
import { courseUrl } from "../../../src/lib/format";

for (const width of [1440, 390]) {
  test(`expanded disclosures use their container width at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    for (const route of [
      "/courses/COMPSCI_300",
      "/departments/COMPSCI",
      "/instructors/HOBBES_LEGAULT",
    ]) {
      await page.goto(route);
      await expect(page.locator("html")).toHaveAttribute(
        "data-hydrated",
        "true",
      );
      // Opening grade details mounts another set of disclosures; opening evidence
      // loads nested source records. Audit both levels after those updates settle.
      for (let pass = 0; pass < 3; pass++) {
        await page
          .locator("details")
          .evaluateAll((elements) =>
            elements.forEach((element) => (element.open = true)),
          );
        await page.waitForTimeout(350);
      }
      if (route.startsWith("/courses/")) {
        await expect(page.locator(".comparison-method")).toBeVisible();
        await expect(page.locator(".benchmark-note")).toBeVisible();
        await expect(page.locator(".outcomes-table")).toBeVisible();
        await expect(
          page.getByText("About this estimate", { exact: true }),
        ).toBeVisible();
        await page
          .locator(".comparison-method")
          .screenshot({
            path: `test-results/comparison-expanded-${width}.png`,
          });
      } else if (route.startsWith("/departments/")) {
        await expect(
          page.getByText("About these statistics", { exact: true }),
        ).toBeVisible();
      } else {
        await expect(page.locator(".rating-method")).toBeVisible();
      }
      const failures = await page.locator("details p").evaluateAll((elements) =>
        elements.flatMap((element) => {
          if (!element.getClientRects().length) return [];
          const rect = element.getBoundingClientRect();
          const parent = element.parentElement!;
          const style = getComputedStyle(parent);
          const available =
            parent.clientWidth -
            parseFloat(style.paddingLeft) -
            parseFloat(style.paddingRight);
          const label = element
            .closest("details")
            ?.querySelector("summary")?.textContent;
          return Math.abs(rect.width - available) > 2 ||
            element.scrollWidth > element.clientWidth + 1
            ? [
                {
                  label,
                  width: rect.width,
                  available,
                  text: element.textContent?.slice(0, 80),
                },
              ]
            : [];
        }),
      );
      expect(failures, route).toEqual([]);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
        route,
      ).toBeLessThanOrEqual(width);
    }
  });
}

test("course reading and prerequisite hierarchy stay clear across screen sizes", async ({
  page,
}) => {
  const enriched = importedCourse(
    "json_array_length(payload,'$.llm_assumed_background') > 0 AND json_array_length(payload,'$.requirements.nodes') > 1",
  );
  for (const code of [
    "MATH_222",
    "COMPSCI_300",
    courseUrl(enriched.course_id).split("/").at(-1)!,
  ]) {
    await page.goto(`/courses/${code}`);
    await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await expect(page.locator(".catalog-description p")).toBeVisible();
      const document = await (
        await page.request.get(`/courses/${code}.json`)
      ).json();
      await expect(
        page.getByRole("complementary", { name: "Helpful background" }),
      ).toHaveCount(document.data.course.llm_assumed_background.length ? 1 : 0);
      await expect(page.locator(".course-facts details")).toHaveCount(0);
      await expect(
        page
          .locator("#requirements > .panel-heading")
          .getByRole("link", { name: "Course map" }),
      ).toBeVisible();
      if (code === "MATH_222") {
        await expect(page.locator(".requirements-source")).toHaveText(
          "MATH 217 or 221. MATH 211 or 213 does not fulfill the requisite.",
        );
        await expect(
          page.getByRole("region", { name: "Prerequisite relationships" }),
        ).toContainText("MATH 211 or 213 does not fulfill the requisite.");
      }
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
    }
  }
});
