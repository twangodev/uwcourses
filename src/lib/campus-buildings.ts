import data from "$lib/assets/campus-buildings.json";

type Point = number[];
export interface Footprint {
  id: string;
  name: string;
  points: Point[];
  polygons?: Point[][][];
  names?: string[];
  sourceUrl?: string;
}
const imported = import.meta.glob<{ buildings: Footprint[] }>(
  "/.site/import/buildings.json",
  { eager: true, import: "default" },
);
const official = Object.values(imported)[0]?.buildings ?? [];
export const hasOfficialBuildings = official.length > 0;
const defaultFootprints: Footprint[] = hasOfficialBuildings
  ? official
  : data.buildings;
interface Activity {
  name: string;
  x: number;
  y: number;
  count: number;
}
const normalize = (name: string) =>
  name.toLowerCase().replace(/[^a-z0-9]/g, "");
function contains(points: Point[], x: number, y: number) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i],
      [xj, yj] = points[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi)
      inside = !inside;
  }
  return inside;
}
function distance(points: Point[], x: number, y: number) {
  let best = Infinity;
  for (let i = 1; i < points.length; i++) {
    const [ax, ay] = points[i - 1],
      [bx, by] = points[i];
    const dx = bx - ax,
      dy = by - ay;
    const t = Math.max(
      0,
      Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy || 1)),
    );
    best = Math.min(best, Math.hypot(x - ax - t * dx, y - ay - t * dy));
  }
  return best;
}
// Names handle courtyard centroids; geometry handles source naming differences.
// A nearby polygon is accepted only within ~15 m and without a competing match.
export function buildingOutlines(
  activity: Activity[],
  footprints: Footprint[] = defaultFootprints,
) {
  const result = new Map<
    string,
    { id: string; name: string; names: string[]; count: number; path: string }
  >();
  for (const building of activity) {
    const candidates = footprints.map((footprint) => ({
      footprint,
      distance: Math.min(
        ...(footprint.polygons ?? [[footprint.points]]).map((rings) =>
          distance(rings[0], building.x, building.y),
        ),
      ),
    }));
    const named = candidates.filter(
      (c) =>
        c.footprint.name &&
        (c.footprint.names ?? [c.footprint.name]).some(
          (name) => normalize(name) === normalize(building.name),
        ) &&
        c.distance < 30,
    );
    const containing = candidates.filter((c) =>
      (c.footprint.polygons ?? [[c.footprint.points]]).some(
        (rings) =>
          contains(rings[0], building.x, building.y) &&
          !rings
            .slice(1)
            .some((ring) => contains(ring, building.x, building.y)),
      ),
    );
    const nearest = candidates.sort((a, b) => a.distance - b.distance);
    const match =
      named.length === 1
        ? named[0]
        : containing.length === 1
          ? containing[0]
          : !containing.length &&
              nearest[0]?.distance <= 5 &&
              (!nearest[1] || nearest[1].distance - nearest[0].distance > 1)
            ? nearest[0]
            : null;
    if (!match) continue;
    const footprint = match.footprint;
    const existing = result.get(footprint.id);
    if (existing) {
      existing.count += building.count;
      existing.names.push(building.name);
    } else
      result.set(footprint.id, {
        id: footprint.id,
        name: building.name,
        names: [building.name],
        count: building.count,
        path: (footprint.polygons ?? [[footprint.points]])
          .flat()
          .map((ring) => "M" + ring.map((p) => p.join(",")).join("L") + "Z")
          .join(""),
      });
  }
  return [...result.values()];
}
