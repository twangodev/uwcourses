import { expect, it } from "vitest";
import { openapiSpec } from "../../src/lib/api/openapi";
import { documentSchemas } from "../../src/lib/api/schemas";
it("publishes resolvable schemas with unique operations for every document format", () => {
  const spec = openapiSpec();
  const ids = Object.values(spec.paths).map(
    (path: any) => path.get.operationId,
  );
  expect(new Set(ids).size).toBe(41);
  expect(spec.paths["/api/facets"]).toBeDefined();
  function walk(value: unknown) {
    if (!value || typeof value !== "object") return;
    if ("$ref" in value) {
      const ref = String(value.$ref);
      expect(ref).toMatch(/^#\/components\/schemas\//);
      expect(spec.components.schemas[ref.split("/").at(-1)!]).toBeDefined();
    }
    Object.values(value).forEach(walk);
  }
  walk(spec);
  expect(spec.components.schemas.Course).toHaveProperty("properties.llm_model");
  expect(
    documentSchemas.Course.safeParse({ schema_version: 1, data: {} }).success,
  ).toBe(false);
});
