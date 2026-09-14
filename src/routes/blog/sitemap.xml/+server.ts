import { posts } from "$lib/server/blog";
import { absoluteUrl } from "$lib/seo";

export const prerender = true;
export function GET() {
  const urls = [{ slug: "", date: undefined }, ...posts];
  return new Response(
    `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls.map((post) => `<url><loc>${absoluteUrl(`/blog${post.slug ? `/${post.slug}` : ""}`)}</loc>${post.date ? `<lastmod>${post.date}</lastmod>` : ""}</url>`).join("")}</urlset>`,
    { headers: { "Content-Type": "application/xml; charset=utf-8" } },
  );
}
