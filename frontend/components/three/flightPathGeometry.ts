/**
 * Converts a GPS path ([lat, lon, alt_m][]) into local 3D scene coordinates.
 *
 * Raw lat/lon degrees aren't usable directly as 3D axes — a degree of
 * longitude covers a different real-world distance than a degree of
 * latitude depending on how far from the equator you are. This projects
 * onto a local flat-earth approximation (accurate enough for any single
 * flight, which never spans more than a few kilometres), centers the path
 * at the origin, and applies a vertical exaggeration factor so altitude
 * changes are visually legible even when the flight covered much more
 * horizontal distance than vertical — the same technique flight-log
 * visualizers commonly use; this is a diagnostic aid, not a literal
 * to-scale model.
 */

const METERS_PER_DEG_LAT = 111_320;
const VERTICAL_EXAGGERATION = 3;
const TARGET_WORLD_SPAN = 3.2; // fit the longest horizontal axis to roughly this many world units

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

export function buildFlightPathScene(gpsPath: [number, number, number][]): FlightPathScene | null {
  if (!gpsPath || gpsPath.length === 0) return null;

  const refLat = gpsPath[0][0];
  const refLon = gpsPath[0][1];
  const refLatRad = (refLat * Math.PI) / 180;
  const metersPerDegLon = METERS_PER_DEG_LAT * Math.cos(refLatRad);

  const minAlt = Math.min(...gpsPath.map((p) => p[2]));
  const maxAlt = Math.max(...gpsPath.map((p) => p[2]));

  const raw = gpsPath.map(([lat, lon, alt]) => ({
    x: (lon - refLon) * metersPerDegLon,
    z: -(lat - refLat) * METERS_PER_DEG_LAT,
    y: (alt - minAlt) * VERTICAL_EXAGGERATION,
  }));

  const xs = raw.map((p) => p.x);
  const zs = raw.map((p) => p.z);
  const spanX = Math.max(...xs) - Math.min(...xs) || 1;
  const spanZ = Math.max(...zs) - Math.min(...zs) || 1;
  const centerX = (Math.max(...xs) + Math.min(...xs)) / 2;
  const centerZ = (Math.max(...zs) + Math.min(...zs)) / 2;

  const scale = TARGET_WORLD_SPAN / Math.max(spanX, spanZ);

  const points = raw.map((p) => ({
    x: (p.x - centerX) * scale,
    y: p.y * scale,
    z: (p.z - centerZ) * scale,
  }));

  return { points, maxAltitudeM: maxAlt - minAlt, scale };
}

export type PathColorMode = "standard" | "wind" | "signal";

// 3-stop gradients, [r,g,b] in 0-1 range (drei's <Line vertexColors> expects this).
const WIND_GRADIENT: [number, number, number][] = [
  [0.11, 0.32, 0.85], // calm — blue
  [0.9, 0.75, 0.1],   // moderate — amber
  [0.95, 0.15, 0.15], // strong — red
];
// Signal quality is HDOP — LOWER is better, so the gradient runs good→bad
// as the value increases, same direction as wind speed.
const SIGNAL_GRADIENT: [number, number, number][] = [
  [0.05, 0.85, 0.45], // good (low HDOP) — green
  [0.9, 0.75, 0.1],   // caution — amber
  [0.95, 0.15, 0.15], // poor (high HDOP) — red
];

function lerpColor(a: [number, number, number], b: [number, number, number], t: number): [number, number, number] {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

function valueToGradientColor(
  value: number,
  min: number,
  max: number,
  gradient: [number, number, number][]
): [number, number, number] {
  const span = max - min || 1;
  const t = Math.min(1, Math.max(0, (value - min) / span));
  const segments = gradient.length - 1;
  const segT = t * segments;
  const idx = Math.min(segments - 1, Math.floor(segT));
  return lerpColor(gradient[idx], gradient[idx + 1], segT - idx);
}

/**
 * Per-point [r,g,b] colors for the flight path line, or null for "standard"
 * mode (a flat colour, handled by the caller). Values with no reading at
 * a given point fall back to a neutral grey rather than breaking the
 * gradient — real logs often have gaps (e.g. wind estimate not available
 * until the EKF has enough data to converge).
 */
export function buildPathColors(
  mode: PathColorMode,
  values: (number | null | undefined)[] | null | undefined
): [number, number, number][] | null {
  if (mode === "standard" || !values || values.length === 0) return null;

  const present = values.filter((v): v is number => v !== null && v !== undefined);
  if (present.length === 0) return null;

  const min = Math.min(...present);
  const max = Math.max(...present);
  const gradient = mode === "wind" ? WIND_GRADIENT : SIGNAL_GRADIENT;
  const NEUTRAL: [number, number, number] = [0.45, 0.45, 0.5];

  return values.map((v) => (v === null || v === undefined ? NEUTRAL : valueToGradientColor(v, min, max, gradient)));
}
