// GPS path ([lat, lon, alt_m][]) -> local scene coordinates, plus the colour ramps the
// map and the 3D view share. Flat-earth projection is fine at single-flight scale;
// altitude is exaggerated 3x so climbs stay visible next to long horizontal legs.

const METERS_PER_DEG_LAT = 111_320;
const VERTICAL_EXAGGERATION = 3;
const TARGET_WORLD_SPAN = 3.2; // longest horizontal axis, in world units

export const MAX_PATH_POINTS = 1000;

export interface ScenePoint {
  x: number;
  y: number;
  z: number;
}

export interface FlightPathScene {
  points: ScenePoint[];
  maxAltitudeM: number;
  scale: number;
}

// spread operators blow the call stack past ~100k points, so plain loops
export function minMax(values: number[]): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return [lo, hi];
}

// evenly spaced indices, always keeping the first and last point
export function sampleIndices(n: number, max = MAX_PATH_POINTS): number[] {
  if (n <= max) return Array.from({ length: n }, (_, i) => i);
  const out: number[] = [];
  const step = (n - 1) / (max - 1);
  for (let k = 0; k < max; k++) out.push(Math.round(k * step));
  return out;
}

export function buildFlightPathScene(gpsPath: [number, number, number][]): FlightPathScene | null {
  if (!gpsPath || gpsPath.length === 0) return null;

  const refLat = gpsPath[0][0];
  const refLon = gpsPath[0][1];
  const metersPerDegLon = METERS_PER_DEG_LAT * Math.cos((refLat * Math.PI) / 180);
  const [minAlt, maxAlt] = minMax(gpsPath.map((p) => p[2]));

  const raw = gpsPath.map(([lat, lon, alt]) => ({
    x: (lon - refLon) * metersPerDegLon,
    z: -(lat - refLat) * METERS_PER_DEG_LAT,
    y: (alt - minAlt) * VERTICAL_EXAGGERATION,
  }));

  const [x0, x1] = minMax(raw.map((p) => p.x));
  const [z0, z1] = minMax(raw.map((p) => p.z));
  const scale = TARGET_WORLD_SPAN / Math.max(x1 - x0 || 1, z1 - z0 || 1);
  const cx = (x0 + x1) / 2;
  const cz = (z0 + z1) / 2;

  const points = raw.map((p) => ({
    x: (p.x - cx) * scale,
    y: p.y * scale,
    z: (p.z - cz) * scale,
  }));

  return { points, maxAltitudeM: maxAlt - minAlt, scale };
}

export type PathColorMode = "standard" | "wind" | "signal";
type RGB = [number, number, number];

// Sequential, not the alert colours: a strong wind or a high HDOP is data here, not a
// warning. Truncated viridis, light end = high value.
const RAMP: RGB[] = [
  [0.23, 0.32, 0.55],
  [0.13, 0.57, 0.55],
  [0.99, 0.91, 0.15],
];

export const RAMP_CSS = "linear-gradient(90deg, rgb(59,82,139), rgb(33,145,140), rgb(253,231,37))";

export function rampColour(t: number): RGB {
  const c = Math.min(1, Math.max(0, t)) * (RAMP.length - 1);
  const i = Math.min(RAMP.length - 2, Math.floor(c));
  const f = c - i;
  const a = RAMP[i];
  const b = RAMP[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

const NEUTRAL: RGB = [0.45, 0.47, 0.5];

// 0-1 position of each value between the path's min and max; null where there's no reading
export function normaliseValues(values: (number | null | undefined)[] | null | undefined): (number | null)[] | null {
  if (!values || values.length === 0) return null;
  const present = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (present.length === 0) return null;
  const [lo, hi] = minMax(present);
  const span = hi - lo || 1;
  return values.map((v) => (typeof v === "number" && Number.isFinite(v) ? (v - lo) / span : null));
}

// Per-point [r,g,b] (0-1) for drei's <Line vertexColors>, or null in standard mode.
// Gaps (no wind estimate yet, etc.) get a neutral grey instead of breaking the ramp.
export function buildPathColors(
  mode: PathColorMode,
  values: (number | null | undefined)[] | null | undefined
): RGB[] | null {
  if (mode === "standard") return null;
  const t = normaliseValues(values);
  return t ? t.map((v) => (v === null ? NEUTRAL : rampColour(v))) : null;
}

export function rgbCss([r, g, b]: RGB): string {
  return `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
}
