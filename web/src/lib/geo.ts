// Canada's provinces for the Insights maps. The shapes are web/public/canada-provinces.json: Natural Earth
// 1:50m admin-1 states and provinces (public domain, naturalearthdata.com), Canada only, simplified.
// Projection: Lambert conformal conic with Statistics Canada's parameters (parallels 49° and 77° N).

export type Ring = [number, number][];
export type Province = { code: string; name: string; polygons: Ring[] };

const rad = Math.PI / 180;
const [P1, P2, LAT0, LON0] = [49 * rad, 77 * rad, 63.390675 * rad, -91.866667 * rad];
const t = (phi: number) => Math.tan(Math.PI / 4 + phi / 2);
const N = Math.log(Math.cos(P1) / Math.cos(P2)) / Math.log(t(P2) / t(P1));
const F = (Math.cos(P1) * Math.pow(t(P1), N)) / N;
const RHO0 = F / Math.pow(t(LAT0), N);

/** Longitude, latitude (degrees) to plane units (x east, y north; about -0.5..0.5 across Canada). */
export function project(lon: number, lat: number): [number, number] {
  const rho = F / Math.pow(t(lat * rad), N);
  const a = N * (lon * rad - LON0);
  return [rho * Math.sin(a), RHO0 - rho * Math.cos(a)];
}

let shapes: Promise<Province[]> | null = null;

/** The provinces, projected, fetched once per page load. */
export function loadProvinces(): Promise<Province[]> {
  shapes ??= fetch("/canada-provinces.json")
    .then((r) => r.json())
    .then((fc: { features: { properties: { code: string; name: string }; geometry: { coordinates: [number, number][][][] } }[] }) =>
      fc.features.map((f) => ({
        code: f.properties.code,
        name: f.properties.name,
        polygons: f.geometry.coordinates.map((poly) => poly[0].map(([lon, lat]) => project(lon, lat))),
      })),
    );
  return shapes;
}

/** Bounds of every ring: [minX, minY, maxX, maxY]. */
export function bounds(ps: Province[]): [number, number, number, number] {
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const p of ps) for (const r of p.polygons) for (const [x, y] of r) [x0, y0, x1, y1] = [Math.min(x0, x), Math.min(y0, y), Math.max(x1, x), Math.max(y1, y)];
  return [x0, y0, x1, y1];
}

/** Area-weighted centre of a province's largest polygon: where its label and dots go. */
export function anchor(p: Province): [number, number] {
  let best: Ring = p.polygons[0];
  let bestA = 0;
  for (const r of p.polygons) {
    const a = Math.abs(area(r));
    if (a > bestA) [best, bestA] = [r, a];
  }
  const A = area(best);
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < best.length - 1; i++) {
    const [x0, y0] = best[i];
    const [x1, y1] = best[i + 1];
    const k = x0 * y1 - x1 * y0;
    cx += (x0 + x1) * k;
    cy += (y0 + y1) * k;
  }
  return [cx / (6 * A), cy / (6 * A)];
}

function area(r: Ring): number {
  let s = 0;
  for (let i = 0; i < r.length - 1; i++) s += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1];
  return s / 2;
}

/** SVG path for a province in a viewBox where x grows right and y grows down. */
export function svgPath(p: Province, fit: (x: number, y: number) => [number, number]): string {
  return p.polygons.map((r) => "M" + r.map(([x, y]) => fit(x, y).map((v) => v.toFixed(1)).join(",")).join("L") + "Z").join("");
}

/** Local weekday (Mon..Sun) and minutes since midnight at instant `t` in time zone `tz`. */
export function localTime(t: number, tz: string): { day: string; minutes: number; label: string } {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(t);
  const get = (k: string) => parts.find((x) => x.type === k)?.value ?? "";
  const h = Number(get("hour"));
  const m = Number(get("minute"));
  return { day: get("weekday").slice(0, 3), minutes: h * 60 + m, label: `${get("weekday").slice(0, 3)} ${get("hour")}:${get("minute")}` };
}
