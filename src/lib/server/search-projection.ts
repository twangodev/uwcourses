import published from "../../../.site/import/status.json";
import type { Status } from "$lib/types";
const status: Status = published;
export function searchProjection(term: string) {
  return {
    available: status.search_projection?.version === 1,
    window: status.search_projection?.version === 1 && status.search_projection.terms.includes(term),
  };
}
