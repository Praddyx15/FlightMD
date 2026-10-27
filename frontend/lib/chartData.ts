import type { Finding } from "./types";
import { isNum } from "./format";

// chart_data is an untyped dict from the analysers. Everything is checked here, once:
// non-numbers and nulls become null (drawn as a gap, never as 0), wrong shapes give no chart.

export interface Series {
  key: string;
  label: string;
  values: (number | null)[];
  axis?: "left" | "right";
  step?: boolean;
}

export interface TimeChartSpec {
  kind: "time";
  key: string;
  category: Finding["category"];
  title: string;
  t: number[]; // log-relative seconds
  series: Series[];
  leftUnit?: string;
  rightUnit?: string;
  refLines?: { y: number; label: string; axis?: "left" | "right" }[];
}

export interface SpectrumChartSpec {
  kind: "spectrum";
  key: string;
  category: Finding["category"];
  title: string;
  freq: number[];
  amp: (number | null)[];
  peakHz: number | null;
}

export type ChartSpec = TimeChartSpec | SpectrumChartSpec;

const MAX_POINTS = 500;

type Dict = Record<string, unknown>;

const isDict = (v: unknown): v is Dict => typeof v === "object" && v !== null && !Array.isArray(v);

function nums(v: unknown): (number | null)[] {
  return Array.isArray(v) ? v.map((x) => (isNum(x) ? x : null)) : [];
}

// one index set for every series so they stay alligned
function pickIndices(t: (number | null)[]): number[] {
  const idx: number[] = [];
  t.forEach((x, i) => {
    if (x !== null) idx.push(i);
  });
  if (idx.length <= MAX_POINTS) return idx;
  const step = idx.length / MAX_POINTS;
  const out: number[] = [];
  for (let k = 0; k < MAX_POINTS; k++) out.push(idx[Math.floor(k * step)]);
  return out;
}

function timeSpec(
  key: string,
  category: Finding["category"],
  title: string,
  rawT: unknown,
  series: Series[],
  extra: Partial<TimeChartSpec> = {}
): TimeChartSpec | null {
  const tMs = nums(rawT);
  const idx = pickIndices(tMs);
  const usable = series.filter((s) => s.values.some((v) => v !== null));
  if (idx.length < 2 || usable.length === 0) return null;
  return {
    kind: "time",
    key,
    category,
    title,
    t: idx.map((i) => (tMs[i] as number) / 1000),
    series: usable.map((s) => ({ ...s, values: idx.map((i) => s.values[i] ?? null) })),
    ...extra,
  };
}

export function chartSpecsFor(f: Finding): ChartSpec[] {
  const cd = f.chart_data;
  // console.log(f.category, Object.keys(cd ?? {}))
  if (!isDict(cd)) return [];

  switch (f.category) {
    case "oscillation": {
      const freq = nums(cd.frequencies);
      const amp = nums(cd.amplitudes);
      const n = Math.min(freq.length, amp.length);
      const keep: number[] = [];
      for (let i = 0; i < n; i++) if (freq[i] !== null) keep.push(i);
      if (keep.length < 2) return [];
      const axis = typeof cd.axis === "string" ? cd.axis : "";
      return [{
        kind: "spectrum",
        key: `oscillation:${axis}`,
        category: f.category,
        title: `Frequency spectrum, ${axis || "rate"} axis`,
        freq: keep.map((i) => freq[i] as number),
        amp: keep.map((i) => amp[i]),
        peakHz: isNum(cd.peak_hz) ? cd.peak_hz : null,
      }];
    }

    case "vibration": {
      // current analyser: { instances: { sensor_accel: {timestamps,x,y,z}, ... } }
      const sources: [string, Dict][] = isDict(cd.instances)
        ? Object.entries(cd.instances).filter((e): e is [string, Dict] => isDict(e[1]))
        : [["", cd]];
      return sources.slice(0, 3).flatMap(([name, d]) => {
        const spec = timeSpec(
          `vibration:${name}`,
          f.category,
          `IMU acceleration${name ? ` (${name})` : ""}`,
          d.timestamps,
          [
            { key: "x", label: "X", values: nums(d.x) },
            { key: "y", label: "Y", values: nums(d.y) },
            { key: "z", label: "Z", values: nums(d.z) },
          ],
          { leftUnit: "m/s²" }
        );
        return spec ? [spec] : [];
      });
    }

    case "battery": {
      const spec = timeSpec("battery", f.category, "Battery voltage and current", cd.timestamps, [
        { key: "v", label: "Voltage", values: nums(cd.voltage), axis: "left" },
        { key: "i", label: "Current", values: nums(cd.current), axis: "right" },
      ], { leftUnit: "V", rightUnit: "A" });
      return spec ? [spec] : [];
    }

    case "gps": {
      const spec = timeSpec("gps", f.category, "GPS satellites and HDOP", cd.timestamps, [
        { key: "sats", label: "Satellites", values: nums(cd.satellites), axis: "left", step: true },
        { key: "hdop", label: "HDOP", values: nums(cd.hdop), axis: "right" },
      ], { refLines: [{ y: 2, label: "HDOP 2", axis: "right" }] });
      return spec ? [spec] : [];
    }

    case "ekf": {
      const ref = [{ y: 1, label: "Test limit 1.0" }];
      if (isDict(cd.innov_ratios)) {
        const series = Object.entries(cd.innov_ratios)
          .slice(0, 6)
          .map(([k, v]) => ({ key: k, label: k, values: nums(v) }));
        const spec = timeSpec("ekf", f.category, "EKF innovation test ratios", cd.timestamps, series, { refLines: ref });
        return spec ? [spec] : [];
      }
      if (cd.ratio !== undefined) {
        const col = typeof cd.col === "string" ? cd.col : "ratio";
        const spec = timeSpec(`ekf:${col}`, f.category, `EKF test ratio: ${col}`, cd.timestamps, [
          { key: "ratio", label: col, values: nums(cd.ratio) },
        ], { refLines: ref });
        return spec ? [spec] : [];
      }
      return [];
    }

    case "motors": {
      if (!isDict(cd.rpm_per_motor)) return [];
      const series = Object.entries(cd.rpm_per_motor)
        .slice(0, 8)
        .map(([k, v], i) => ({ key: k, label: `Motor ${i + 1}`, values: nums(v) }));
      const spec = timeSpec("motors", f.category, "Motor RPM", cd.timestamps, series, { leftUnit: "rpm" });
      return spec ? [spec] : [];
    }

    default:
      return [];
  }
}

export interface ReportCharts {
  specs: ChartSpec[];
  // finding id -> chart key it can be shown on
  chartOf: Map<string, string>;
  // chart key -> findings drawn on it
  findingsOn: Map<string, Finding[]>;
}

// Findings in one category share chart_data, so each chart is built once. A finding
// without chart_data still lands on its category's time chart.
export function collectCharts(findings: Finding[]): ReportCharts {
  const specs: ChartSpec[] = [];
  const seen = new Set<string>();
  const chartOf = new Map<string, string>();
  const findingsOn = new Map<string, Finding[]>();

  const attach = (f: Finding, key: string) => {
    if (!chartOf.has(f.id)) chartOf.set(f.id, key);
    const list = findingsOn.get(key) ?? [];
    list.push(f);
    findingsOn.set(key, list);
  };

  for (const f of findings) {
    let built: ChartSpec[] = [];
    try {
      built = chartSpecsFor(f);
    } catch {
      built = []; // malformed chart_data: no chart, never a crash
    }
    for (const s of built) {
      if (!seen.has(s.key)) {
        seen.add(s.key);
        specs.push(s);
      }
      attach(f, s.key);
    }
  }

  for (const f of findings) {
    if (chartOf.has(f.id)) continue;
    const s = specs.find((x) => x.kind === "time" && x.category === f.category);
    if (s) attach(f, s.key);
  }

  return { specs, chartOf, findingsOn };
}
