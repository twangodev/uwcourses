import type { Component } from "svelte";
import type { PageLoad } from "./$types";

const components = import.meta.glob<{ default: Component }>(
  "/src/content/blog/*.svx",
);
export const load: PageLoad = async ({ data }) => {
  const { default: component } = await components[data.post.path]();
  return { ...data, component };
};
