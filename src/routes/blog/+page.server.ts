import { posts } from "$lib/server/blog";

export const prerender = true;
export function load() {
  return { posts };
}
