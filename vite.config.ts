import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vitest/config";
import { socialImagesDev } from "./web/social-images.mjs";
import { dataAssetsDev } from "./web/data-assets.mjs";
import { watchDirectories } from "./web/watch-directories";

export default defineConfig({
  plugins: [dataAssetsDev(), socialImagesDev(), sveltekit()],
  ssr: { noExternal: ["@lucide/svelte"] },
  server: {
    watch: watchDirectories({
      root: new URL(".", import.meta.url),
      include: ["src", "web", "static", ".svelte-kit/generated"],
      exclude: ["static/data"],
      includeRootFiles: true,
    }),
  },
  test: { include: ["web/tests/**/*.test.ts"] },
});
