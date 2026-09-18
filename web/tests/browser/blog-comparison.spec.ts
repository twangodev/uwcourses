import { expect, test } from "@playwright/test";

const path = "/blog/stat-301-vs-stat-371-uw-madison";
test("comparison retains sources and evidence without JavaScript", async ({
  browser,
  request,
}) => {
  const context = await browser.newContext({
    javaScriptEnabled: false,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const response = await page.goto(path);
  expect(response?.status()).toBe(200);
  await expect(page.locator("h1")).toContainText("STAT 301 vs. STAT 371");
  await expect(page.locator(".blog-prose")).toContainText(
    "substituted for one lecture",
  );
  await page.getByText("How we checked the evidence", { exact: true }).click();
  await expect(
    page.getByText("older comments outside our window were not used", {
      exact: false,
    }),
  ).toBeVisible();
  for (const code of ["STAT_301", "STAT_371"]) {
    await expect(
      page.locator(`.blog-prose a[href="/courses/${code}"]`).first(),
    ).toBeVisible();
    expect((await request.get(`/courses/${code}`)).status()).toBe(200);
  }
  const data = await (await request.get(path + ".json")).json();
  expect(data.courses.map((c: any) => c.review_records.length)).toEqual([
    40, 68,
  ]);
  expect(data.courses.map((c: any) => c.pooled.n)).toEqual([3898, 5234]);
  await page.screenshot({
    path: "/tmp/stat-comparison-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "/tmp/stat-comparison-mobile.png" });
  await context.close();
});
