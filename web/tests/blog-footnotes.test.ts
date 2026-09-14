import { expect, it } from "vitest";
import { compile, preprocess } from "svelte/compiler";
import config from "../../svelte.config.js";

it("numbers named footnotes and links every repeated reference back uniquely", async () => {
  const result = await preprocess(
    "A claim.[^source]\n\nAnother claim.[^other] Again.[^source]\n\n[^source]: Source with a [link](https://example.com).\n\n[^other]: Another source.",
    config.preprocess,
    { filename: "footnotes.svx" },
  );
  for (const id of [
    "blog-fnref-1-1",
    "blog-fnref-1-2",
    "blog-fnref-2-1",
    "blog-fn-1",
    "blog-fn-2",
  ]) {
    expect(result.code.match(new RegExp(`id="${id}"`, "g"))).toHaveLength(1);
    expect(result.code).toContain(`href="#${id}"`);
  }
  expect(result.code).toContain('aria-label="Footnote 1"');
  expect(result.code).toContain('aria-labelledby="blog-footnotes"');
  expect(result.code).toContain("Notes and sources");
  expect(result.code).not.toContain("[^source]");
  expect(() => compile(result.code, { generate: "server" })).not.toThrow();
});
