// One place for how numbers, times and dates look. Units always, thousands separators,
// "—" for missing. Pair the output with the .num class for tabular figures.

const nfCache = new Map<string, Intl.NumberFormat>();

function nf(digits: number, minDigits = 0) {
  const key = `${digits}:${minDigits}`;
  let f = nfCache.get(key);
  if (!f) {
    f = new Intl.NumberFormat("en", {
      maximumFractionDigits: digits,
      minimumFractionDigits: minDigits,
    });
    nfCache.set(key, f);
  }
  return f;
}

export const DASH = "—";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export function fmtNum(v: number | null | undefined, digits = 1, unit?: string): string {
  if (!isNum(v)) return DASH;
  const s = nf(digits).format(v);
  return unit ? `${s} ${unit}` : s;
}

// fixed decimals, for columns where values must line up
export function fmtFixed(v: number | null | undefined, digits: number, unit?: string): string {
  if (!isNum(v)) return DASH;
  const s = nf(digits, digits).format(v);
  return unit ? `${s} ${unit}` : s;
}

export function fmtInt(v: number | null | undefined, unit?: string): string {
  return fmtNum(isNum(v) ? Math.round(v) : v, 0, unit);
}

export function fmtScore(v: number | null | undefined): string {
  return isNum(v) ? `${Math.round(v)} / 100` : DASH;
}

export function fmtDelta(v: number | null | undefined, digits = 1, unit?: string): string {
  if (!isNum(v)) return DASH;
  const sign = v > 0 ? "+" : v < 0 ? "−" : "±";
  return `${sign}${fmtNum(Math.abs(v), digits, unit)}`;
}

// log-relative position, e.g. 1:05 or 1:02:05; sub-second precision only when asked
export function fmtClock(seconds: number | null | undefined, decimals = 0): string {
  if (!isNum(seconds)) return DASH;
  const neg = seconds < 0;
  let s = Math.abs(seconds);
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  s -= m * 60;
  const secStr = decimals > 0 ? s.toFixed(decimals).padStart(3 + decimals, "0") : String(Math.floor(s)).padStart(2, "0");
  const body = h > 0 ? `${h}:${String(m).padStart(2, "0")}:${secStr}` : `${m}:${secStr}`;
  return neg ? `-${body}` : body;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (!isNum(seconds)) return DASH;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h} h ${String(m).padStart(2, "0")} min`;
  if (m > 0) return `${m} min ${String(s).padStart(2, "0")} s`;
  return `${s} s`;
}

export function fmtBytes(bytes: number | null | undefined): string {
  if (!isNum(bytes)) return DASH;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return fmtNum(bytes / 1024, 1, "KB");
  return fmtNum(bytes / 1024 / 1024, 1, "MB");
}

// Older reports carry a bogus offset like "19800" in log_start_utc; only a real
// ISO date-time counts.
export function parseIsoDate(s: string | null | undefined): Date | null {
  if (!s || !/^\d{4}-\d{2}-\d{2}T/.test(s)) return null;
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtDateTime(d: Date | null | undefined): string {
  if (!d) return DASH;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

export function fmtUtc(d: Date | null | undefined): string {
  if (!d) return DASH;
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function fmtDate(d: Date | null | undefined): string {
  if (!d) return DASH;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// today in the users zone (toISOString would give the UTC date)
export function localIsoDate(d = new Date()): string {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

// Parameter values as a GCS expects them: no float32 noise (0.15000000596 -> 0.15),
// no exponent notation.
export function fmtParam(v: number): string {
  if (!isNum(v)) return String(v);
  if (Number.isInteger(v)) return String(v);
  const s = String(parseFloat(v.toPrecision(7)));
  if (!s.includes("e")) return s;
  return v.toFixed(10).replace(/0+$/, "").replace(/\.$/, "");
}

// Reports are always SI; conversion happens only here, at display time.
export type UnitSystem = "metric" | "imperial" | "aviation";
export type Quantity = "altitude" | "distance" | "speed" | "temperature";

export const UNIT_SYSTEMS: UnitSystem[] = ["metric", "imperial", "aviation"];

export function isUnitSystem(v: unknown): v is UnitSystem {
  return typeof v === "string" && (UNIT_SYSTEMS as string[]).includes(v);
}

const FT_PER_M = 1 / 0.3048;
const KT_PER_MS = 3600 / 1852;
const MPH_PER_MS = 3600 / 1609.344;

// metric: m, m/s, °C · imperial: ft, mph, °F · aviation: ft, kt, °C
export function toUnit(v: number, q: Quantity, sys: UnitSystem): { value: number; unit: string } {
  if (sys === "metric") {
    return { value: v, unit: q === "speed" ? "m/s" : q === "temperature" ? "°C" : "m" };
  }
  switch (q) {
    case "altitude":
    case "distance":
      return { value: v * FT_PER_M, unit: "ft" };
    case "speed":
      return sys === "aviation" ? { value: v * KT_PER_MS, unit: "kt" } : { value: v * MPH_PER_MS, unit: "mph" };
    case "temperature":
      return sys === "aviation" ? { value: v, unit: "°C" } : { value: (v * 9) / 5 + 32, unit: "°F" };
  }
}

export function fmtQty(v: number | null | undefined, q: Quantity, sys: UnitSystem, digits = 1): string {
  if (!isNum(v)) return DASH;
  const { value, unit } = toUnit(v, q, sys);
  return fmtNum(value, digits, unit);
}
