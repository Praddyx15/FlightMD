import { describe, expect, it } from "vitest";
import { chartSpecsFor, collectCharts, type TimeChartSpec } from "@/lib/chartData";
import { finding } from "./fixtures";

describe("chartSpecsFor", () => {
  it("turns non-numbers into gaps, never zeros", () => {
    const [spec] = chartSpecsFor(finding({
      chart_data: { timestamps: [0, 1000, 2000], voltage: [16.1, null, "x"], current: [10, 11, 12] },
    })) as TimeChartSpec[];
    expect(spec.t).toEqual([0, 1, 2]);
    expect(spec.series[0].values).toEqual([16.1, null, null]);
    expect(spec.title).toEqual({ key: "battery" });
    expect(spec.leftUnit).toBe("V");
  });

  it("downsamples long series to at most 500 points, keeping series aligned", () => {
    const n = 2000;
    const t = Array.from({ length: n }, (_, i) => i * 10);
    const [spec] = chartSpecsFor(finding({
      chart_data: { timestamps: t, voltage: t.map((x) => x / 10), current: t },
    })) as TimeChartSpec[];
    expect(spec.t).toHaveLength(500);
    spec.t.forEach((sec, i) => expect(spec.series[0].values[i]).toBeCloseTo(sec * 100, 6));
  });

  it("drops series with no data and charts with too few points", () => {
    const [spec] = chartSpecsFor(finding({
      chart_data: { timestamps: [0, 1000], voltage: [16, 15.8], current: [null, null] },
    })) as TimeChartSpec[];
    expect(spec.series.map((s) => s.key)).toEqual(["v"]);
    expect(chartSpecsFor(finding({ chart_data: { timestamps: [0], voltage: [16] } }))).toEqual([]);
  });

  it("builds one chart per vibration instance", () => {
    const imu = { timestamps: [0, 1000], x: [1, 2], y: [1, 2], z: [9, 10] };
    const specs = chartSpecsFor(finding({
      category: "vibration",
      chart_data: { instances: { sensor_accel: imu, sensor_accel_1: imu } },
    }));
    expect(specs.map((s) => s.key)).toEqual(["vibration:sensor_accel", "vibration:sensor_accel_1"]);
    expect(specs[1].title).toEqual({ key: "imuNamed", values: { name: "sensor_accel_1" } });
  });

  it("draws the autopilot's vibration metric against its limits", () => {
    const [spec] = chartSpecsFor(finding({
      category: "vibration",
      chart_data: { timestamps: [0, 1000, 2000], vibe: [10, 35, 70], warn: 30, crit: 60, metric: "accel_vibration_metric" },
    })) as TimeChartSpec[];
    expect(spec.series.map((s) => s.key)).toEqual(["vibe"]);
    expect(spec.series[0].values).toEqual([10, 35, 70]);
    expect(spec.refLines?.map((r) => [r.y, r.label.key])).toEqual([[30, "vibeWarn"], [60, "vibeCrit"]]);
    expect(spec.leftUnit).toBe("m/s²");
    expect(spec.title).toEqual({ key: "vibeMetric", values: { metric: "accel_vibration_metric" } });
  });

  it("reads an oscillation spectrum", () => {
    const [spec] = chartSpecsFor(finding({
      category: "oscillation",
      chart_data: { frequencies: [0, 5, 10], amplitudes: [0.1, 0.9, 0.2], peak_hz: 5, axis: "roll" },
    }));
    expect(spec).toMatchObject({
      kind: "spectrum",
      freq: [0, 5, 10],
      peakHz: 5,
      title: { key: "spectrumAxis", values: { axis: "roll" } },
    });
  });

  it("returns nothing for missing or wrongly shaped chart data", () => {
    expect(chartSpecsFor(finding({ chart_data: null }))).toEqual([]);
    expect(chartSpecsFor(finding({ category: "motors", chart_data: { rpm_per_motor: [1, 2] } }))).toEqual([]);
  });
});

describe("collectCharts", () => {
  it("builds each chart once and attaches findings without data to their category chart", () => {
    const data = { timestamps: [0, 1000, 2000], voltage: [16, 15, 14], current: [1, 2, 3] };
    const a = finding({ id: "a", chart_data: data });
    const b = finding({ id: "b", chart_data: data });
    const c = finding({ id: "c", chart_data: null });
    const charts = collectCharts([a, b, c]);
    expect(charts.specs).toHaveLength(1);
    expect(charts.chartOf.get("c")).toBe("battery");
    expect(charts.findingsOn.get("battery")?.map((f) => f.id)).toEqual(["a", "b", "c"]);
  });

  it("never throws on odd chart data", () => {
    const odd = finding({ category: "ekf", chart_data: { innov_ratios: { vel: "nope" }, timestamps: 5 } });
    expect(() => collectCharts([odd])).not.toThrow();
    expect(collectCharts([odd]).specs).toEqual([]);
  });
});
