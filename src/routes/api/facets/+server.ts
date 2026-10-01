import { apiJson } from "$lib/server/api-response";
import { interactionSchemas } from "$lib/api/schemas";
import { assertRevision } from "$lib/server/data";
import { courseDistributions } from "$lib/server/facets";

export async function GET({ url, platform }) {
  const started = performance.now();
  await assertRevision(url, platform);
  return apiJson(
    interactionSchemas.Facets,
    await courseDistributions(url, platform),
    {
      headers: {
        "Cache-Control": "public, max-age=60",
        "Server-Timing": `facets;dur=${(performance.now() - started).toFixed(1)}`,
      },
    },
  );
}
