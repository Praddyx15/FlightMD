import { describe, expect, it } from "vitest";
import {
  buildFlightPathScene,
  buildPathColors,
  minMax,
  normaliseValues,
  rampColour,
  rgbCss,
  sampleIndices,
} from "@/components/three/flightPathGeometry";

describe("sampleIndices", () => {
  it("keeps short paths whole", () => {
    expect(sampleIndices(5)).toEqual([0, 1, 2, 3, 4]);
  });

  it("caps long paths and keeps the first and last point", () => {
    const idx = sampleIndices(10_001, 1000);
    expect(idx).toHaveLength(1000);
    expect(idx[0]).toBe(0);
    expect(idx[idx.length - 1]).toBe(10_000);
  });
});

describe("buildFlightPathScene", () => {
  it("returns null without points", () => {
    expect(buildFlightPathScene([])).toBeNull();
  });

  it("scales the longest horizontal axis to the scene span and centres it", () => {
    const scene = buildFlightPathScene([
      [47.0, 8.0, 400],
      [47.001, 8.0, 410],
    ]);
    expect(scene).not.toBeNull();
    const zs = scene!.points.map((p) => p.z);
    expect(Math.max(...zs) - Math.min(...zs)).toBeCloseTo(3.2, 6);
    expect(zs[0] + zs[1]).toBeCloseTo(0, 6);
    expect(scene!.maxAltitudeM).toBe(10);
    expect(scene!.points[0].y).toBe(0);
  });
});

describe("colour ramps", () => {
  it("finds min and max", () => {
    expect(minMax([3, -1, 7])).toEqual([-1, 7]);
  });

  it("normalises values and keeps gaps", () => {
    expect(normaliseValues([null, 0, 5, 10])).toEqual([null, 0, 0.5, 1]);
    expect(normaliseValues([null, undefined])).toBeNull();
    expect(normaliseValues(null)).toBeNull();
  });

  it("has no colours in standard mode and grey for gaps", () => {
    expect(buildPathColors("standard", [1, 2])).toBeNull();
    const cols = buildPathColors("wind", [0, null, 10]);
    expect(cols?.[0]).toEqual(rampColour(0));
    expect(cols?.[1]).toEqual([0.45, 0.47, 0.5]);
    expect(cols?.[2]).toEqual(rampColour(1));
  });

  it("clamps the ramp and writes css colours", () => {
    expect(rampColour(-1)).toEqual(rampColour(0));
    expect(rgbCss([1, 0, 0.5])).toBe("rgb(255, 0, 128)");
  });
});
