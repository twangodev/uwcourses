import { error } from "@sveltejs/kit";
import { dev } from "$app/environment";
import { allPosts, posts } from "$lib/server/blog";
import type { PageServerLoad } from "./$types";

export const prerender = true;
export const entries = () => posts.map(({ slug }) => ({ slug }));
export const load: PageServerLoad = ({ params }) => {
  const post = (dev ? allPosts : posts).find(
    (post) => post.slug === params.slug,
  );
  if (!post) error(404, "Post not found");
  return { post };
};
