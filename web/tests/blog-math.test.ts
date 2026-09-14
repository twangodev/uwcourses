import { expect, it } from "vitest";
import { preprocess, compile } from "svelte/compiler";
import config from "../../svelte.config.js";

it("preserves quoted strings inside data-backed Markdown expressions", async () => {
  const result = await preprocess(
    `<script>const values = { label: 1234 };</script>\n\nCount: {values['label'].toLocaleString('en-US')}.`,
    config.preprocess,
    { filename: "data-post.svx" },
  );
  expect(() => compile(result.code, { generate: "server" })).not.toThrow();
});

it("compiles inline and display math with braces into valid Svelte", async () => {
  const result = await preprocess(
    String.raw`Inline $E = mc^2$.

$$
\bar{x} = \frac{1}{n} \sum_{i=1}^{n} x_i
$$
`,
    config.preprocess,
    { filename: "math.svx" },
  );
  expect(result.code).toContain("katex-display");
  expect(result.code).toContain("MathML");
  expect(result.code).not.toContain("katex-error");
  expect(() => compile(result.code, { generate: "server" })).not.toThrow();
});
