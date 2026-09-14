import { expect, it } from "vitest";
import { compile, preprocess } from "svelte/compiler";
import config from "../../svelte.config.js";

const sources = import.meta.glob<string>("/src/content/blog/*.svx", {
  query: "?raw",
  import: "default",
  eager: true,
});

it.each(Object.entries(sources))(
  "compiles blog source %s",
  async (filename, source) => {
    const result = await preprocess(source, config.preprocess, { filename });
    expect(() => compile(result.code, { generate: "server" })).not.toThrow();
  },
);
