import { expect, it } from "vitest";
import { isBlogSlug } from "../../src/lib/blog-format";

it("accepts kebab-case post slugs and rejects feed filenames", () => {
  expect(isBlogSlug("welcome")).toBe(true);
  expect(isBlogSlug("stat-301-vs-stat-371-uw-madison")).toBe(true);
  expect(isBlogSlug("rss.xml")).toBe(false);
  expect(isBlogSlug("sitemap.xml")).toBe(false);
});
