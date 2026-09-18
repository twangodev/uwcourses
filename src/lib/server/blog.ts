import { z } from "zod";
import { isBlogSlug } from "$lib/blog-format";

const metadataSchema = z.object({
  title: z.string().trim().min(1),
  description: z.string().trim().min(1),
  date: z.iso.date(),
  draft: z.boolean().default(false),
});

const metadata = import.meta.glob("/src/content/blog/*.svx", {
  eager: true,
  import: "metadata",
});
export const allPosts = Object.entries(metadata)
  .map(([path, value]) => {
    const parsed = metadataSchema.safeParse(value);
    if (!parsed.success)
      throw new Error(
        `Invalid blog metadata in ${path}: ${parsed.error.message}`,
      );
    const slug = path
      .split("/")
      .at(-1)!
      .replace(/\.svx$/, "");
    if (!isBlogSlug(slug)) throw new Error(`Invalid blog slug: ${slug}`);
    return { ...parsed.data, slug, path };
  })
  .sort((a, b) => b.date.localeCompare(a.date) || a.slug.localeCompare(b.slug));

export const posts = allPosts.filter((post) => !post.draft);
