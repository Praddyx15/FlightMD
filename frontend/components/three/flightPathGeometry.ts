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
