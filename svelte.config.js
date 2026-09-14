import adapter from "@sveltejs/adapter-cloudflare";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
import { mdsvex } from "mdsvex";
import remarkMath from "remark-math";
import remarkFootnotes from "remark-footnotes";
import { blogFootnotes } from "./web/blog/footnotes.js";
import rehypeKatexSvelte from "rehype-katex-svelte";
import { assembleAssets } from "./web/assemble-assets.mjs";
const cloudflare = adapter({
  // Build/dev loaders use .site/import/site.sqlite; emulator state need not persist.
  platformProxy: { persist: false },
  config: process.env.WRANGLER_CONFIG || "wrangler.json",
});
export default {
  extensions: [".svelte", ".svx"],
  preprocess: [
    vitePreprocess(),
    mdsvex({
      extensions: [".svx"],
      // Keep quotes in embedded Svelte expressions valid JavaScript.
      smartypants: false,
      remarkPlugins: [remarkMath, remarkFootnotes],
      rehypePlugins: [rehypeKatexSvelte, blogFootnotes],
    }),
  ],
  kit: {
    // Inline route styles to avoid blocking first paint on many small CSS requests.
    inlineStyleThreshold: 32768,
    adapter: {
      ...cloudflare,
      async adapt(builder) {
        await cloudflare.adapt(builder);
        // CI compiles in parallel with data preparation, then assembles before auditing.
        if (process.env.SITE_ASSETS !== "deferred") await assembleAssets();
      },
    },
    prerender: {
      concurrency: 4,
      handleHttpError: "fail",
      handleMissingId: "warn",
      entries: ["*", "/openapi.json"],
    },
  },
};
