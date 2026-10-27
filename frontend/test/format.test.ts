import { describe, expect, it } from "vitest";
import {
  DASH,
  fmtBytes,
  fmtClock,
  fmtDelta,
  fmtDuration,
  fmtFixed,
  fmtInt,
  fmtNum,
  fmtParam,
  fmtQty,
  fmtScore,
  fmtUtc,
  isUnitSystem,
  parseIsoDate,
  toUnit,
} from "@/lib/format";

describe("numbers", () => {
  it("formats with separators and units", () => {
    expect(fmtNum(1234.567, 1)).toBe("1,234.6");
    expect(fmtNum(1234.567, 1, "m")).toBe("1,234.6 m");
    expect(fmtFixed(1.5, 2)).toBe("1.50");
    expect(fmtInt(2.6, "h")).toBe("3 h");
  });

  it("shows a dash for missing values", () => {
    expect(fmtNum(null)).toBe(DASH);
    expect(fmtNum(undefined)).toBe(DASH);
    expect(fmtNum(Number.NaN)).toBe(DASH);
    expect(fmtScore(undefined)).toBe(DASH);
  });

  it("formats scores out of 100, never as a percentage", () => {
    expect(fmtScore(87.4)).toBe("87 / 100");
  });

  it("signs deltas", () => {
    expect(fmtDelta(2.34)).toBe("+2.3");
    expect(fmtDelta(-1)).toBe("−1");
    expect(fmtDelta(0)).toBe("±0");
  });
});

describe("time", () => {
  it("formats log-relative clock positions", () => {
    expect(fmtClock(65)).toBe("1:05");
    expect(fmtClock(3725)).toBe("1:02:05");
    expect(fmtClock(-5)).toBe("-0:05");
    expect(fmtClock(65.5, 1)).toBe("1:05.5");
    expect(fmtClock(null)).toBe(DASH);
  });

  it("formats durations", () => {
    expect(fmtDuration(45)).toBe("45 s");
    expect(fmtDuration(125)).toBe("2 min 05 s");
    expect(fmtDuration(3700)).toBe("1 h 01 min");
  });

  it("accepts only real ISO date-times", () => {
    expect(parseIsoDate("19800")).toBeNull();
    expect(parseIsoDate(null)).toBeNull();
    expect(parseIsoDate("2026-05-01T10:20:30Z")?.toISOString()).toBe("2026-05-01T10:20:30.000Z");
    expect(fmtUtc(new Date("2026-05-01T10:20:30Z"))).toBe("2026-05-01 10:20 UTC");
  });
});

describe("files and parameters", () => {
  it("formats byte sizes", () => {
    expect(fmtBytes(500)).toBe("500 B");
    expect(fmtBytes(2048)).toBe("2 KB");
    expect(fmtBytes(5 * 1024 * 1024)).toBe("5 MB");
  });

  it("drops float32 noise and exponent notation from parameter values", () => {
    expect(fmtParam(0.15000000596046448)).toBe("0.15");
    expect(fmtParam(12)).toBe("12");
    expect(fmtParam(1e-7)).toBe("0.0000001");
  });
});

describe("units", () => {
  it("leaves metric values alone", () => {
    expect(toUnit(100, "altitude", "metric")).toEqual({ value: 100, unit: "m" });
    expect(fmtQty(10, "speed", "metric")).toBe("10 m/s");
    expect(fmtQty(20, "temperature", "metric", 0)).toBe("20 °C");
  });

  it("converts to imperial", () => {
    const alt = toUnit(100, "altitude", "imperial");
    expect(alt.unit).toBe("ft");
    expect(alt.value).toBeCloseTo(328.084, 3);
    expect(fmtQty(10, "speed", "imperial")).toBe("22.4 mph");
    expect(fmtQty(20, "temperature", "imperial", 0)).toBe("68 °F");
    expect(fmtQty(1000, "distance", "imperial", 0)).toBe("3,281 ft");
  });

  it("uses feet and knots but keeps Celsius for aviation", () => {
    expect(fmtQty(10, "speed", "aviation")).toBe("19.4 kt");
    expect(fmtQty(100, "altitude", "aviation", 0)).toBe("328 ft");
    expect(fmtQty(20, "temperature", "aviation", 0)).toBe("20 °C");
  });

  it("shows a dash for missing quantities", () => {
    expect(fmtQty(null, "altitude", "imperial")).toBe(DASH);
  });

  it("recognises unit systems", () => {
    expect(isUnitSystem("imperial")).toBe(true);
    expect(isUnitSystem("furlongs")).toBe(false);
    expect(isUnitSystem(null)).toBe(false);
  });
});
