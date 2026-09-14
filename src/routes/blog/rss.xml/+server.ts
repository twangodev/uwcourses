import { posts } from "$lib/server/blog";
import { blogFeed } from "$lib/server/blog-feed";

export const prerender = true;
export function GET() {
  return new Response(blogFeed(posts), {
    headers: { "Content-Type": "application/rss+xml; charset=utf-8" },
  });
}
