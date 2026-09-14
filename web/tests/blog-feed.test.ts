import { expect, it } from "vitest";
import { blogFeed } from "../../src/lib/server/blog-feed";

it("escapes post metadata and emits canonical links and UTC dates", () => {
  const feed = blogFeed([
    {
      slug: "example",
      title: 'Grades & <courses> "today"',
      description: "A student's guide",
      date: "2026-09-13",
    },
  ]);
  expect(feed).toContain("Grades &amp; &lt;courses&gt; &quot;today&quot;");
  expect(feed).toContain("A student&apos;s guide");
  expect(feed).toContain(
    '<guid isPermaLink="true">https://uwcourses.com/blog/example</guid>',
  );
  expect(feed).toContain("Sun, 13 Sep 2026 00:00:00 GMT");
});

it("supports an empty blog", () => {
  const feed = blogFeed([]);
  expect(feed).toContain("<channel>");
  expect(feed).not.toContain("<item>");
});
