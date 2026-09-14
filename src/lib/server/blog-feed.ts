import { absoluteUrl } from "$lib/seo";

type FeedPost = {
  slug: string;
  title: string;
  description: string;
  date: string;
};
function xml(value: string) {
  return value.replace(
    /[<>&"']/g,
    (char) =>
      ({
        "<": "&lt;",
        ">": "&gt;",
        "&": "&amp;",
        '"': "&quot;",
        "'": "&apos;",
      })[char]!,
  );
}

export function blogFeed(posts: FeedPost[]) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>UW Courses Blog</title>
<link>${absoluteUrl("/blog")}</link>
<description>Updates and notes on exploring UW–Madison courses.</description>
<language>en-us</language>
<atom:link href="${absoluteUrl("/blog/rss.xml")}" rel="self" type="application/rss+xml" />
${posts
  .map((post) => {
    const url = xml(absoluteUrl(`/blog/${post.slug}`));
    return `<item>
<title>${xml(post.title)}</title>
<link>${url}</link>
<guid isPermaLink="true">${url}</guid>
<description>${xml(post.description)}</description>
<pubDate>${new Date(`${post.date}T00:00:00Z`).toUTCString()}</pubDate>
</item>`;
  })
  .join("\n")}
</channel>
</rss>`;
}
