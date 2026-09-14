import { expect, test } from "@playwright/test";
import katex from "katex";

test("RSS is discoverable and contains published posts", async ({
  page,
  request,
}) => {
  await page.goto("/blog");
  await expect(
    page.getByRole("link", { name: "Subscribe via RSS" }),
  ).toHaveAttribute("href", "/blog/rss.xml");
  await expect(
    page.locator('link[type="application/rss+xml"]'),
  ).toHaveAttribute("href", "/blog/rss.xml");
  const response = await request.get("/blog/rss.xml");
  expect(response.headers()["content-type"]).toContain("application/rss+xml");
  const content = await response.text();
  const items = await page.evaluate((content) => {
    const doc = new DOMParser().parseFromString(content, "application/xml");
    if (doc.querySelector("parsererror")) throw new Error("Invalid RSS XML");
    return [...doc.querySelectorAll("item link")].map(
      (link) => link.textContent,
    );
  }, content);
  expect(items).toContain("https://uwcourses.com/blog/welcome");
});

test("KaTeX styles and fonts render wide equations without page overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/blog/welcome");
  await expect(page.locator('html[data-hydrated="true"]')).toBeAttached();
  const equation = katex.renderToString(
    String.raw`\bar{x} = \frac{1}{n} \sum_{i=1}^{n} x_i \qquad a+b+c+d+e+f+g+h+i+j+k+l+m+n`,
    { displayMode: true },
  );
  await page.locator(".blog-prose").evaluate((element, equation) => {
    element.innerHTML = equation;
  }, equation);
  await page.evaluate(() => document.fonts.ready);
  await expect(page.locator(".katex-display")).toHaveCSS("overflow-x", "auto");
  const mathColor = await page
    .locator(".katex")
    .evaluate((element) => getComputedStyle(element).color);
  await expect(page.locator(".katex .accent").first()).toHaveCSS(
    "color",
    mathColor,
  );
  expect(
    await page
      .locator(".katex .mord.mathnormal")
      .first()
      .evaluate((element) => getComputedStyle(element).fontFamily),
  ).toContain("KaTeX_Math");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "/tmp/uw-blog-katex.png", fullPage: true });
});

test("blog navigation renders Markdown and post metadata", async ({ page }) => {
  await page.goto("/blog");
  await expect(
    page.getByRole("heading", { name: "Blog", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Welcome to the UW Courses blog" })
    .click();
  await expect(page).toHaveURL(/\/blog\/welcome$/);
  await expect(
    page.getByRole("heading", { name: "Start exploring" }),
  ).toBeVisible();
  await expect(page).toHaveTitle("Welcome to the UW Courses blog | UW Courses");
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    "https://uwcourses.com/blog/welcome",
  );
  await expect(page.locator('meta[property="og:type"]')).toHaveAttribute(
    "content",
    "article",
  );
  await page.getByRole("link", { name: "All posts" }).click();
  await expect(page).toHaveURL(/\/blog$/);
});

test("blog renders without overflow on mobile in both themes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  for (const path of ["/blog", "/blog/welcome"]) {
    await page.goto(path);
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached();
    for (const dark of [false, true]) {
      await page.evaluate(
        (dark) => document.documentElement.classList.toggle("dark", dark),
        dark,
      );
      await expect(page.locator("h1")).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `/tmp/uw-blog-${path.endsWith("welcome") ? "post" : "index"}-${dark ? "dark" : "light"}.png`,
        fullPage: true,
      });
    }
  }
});

test("unknown posts return 404 and published posts appear in the sitemap", async ({
  request,
}) => {
  expect((await request.get("/blog/does-not-exist")).status()).toBe(404);
  const response = await request.get("/blog/sitemap.xml");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/xml");
  expect(await response.text()).toContain("https://uwcourses.com/blog/welcome");
});
