import type { CSSProperties } from "react";

// series differ by hue and by dash, so they survive greyscale print and colour blindness
export const SERIES_COLOURS = [1, 2, 3, 4, 5, 6].map((n) => `var(--series-${n})`);
export const SERIES_DASHES = ["", "6 3", "2 3", "10 3 2 3", "4 4", "1 2"];

export const seriesColour = (i: number) => SERIES_COLOURS[i % SERIES_COLOURS.length];
export const seriesDash = (i: number) => SERIES_DASHES[i % SERIES_DASHES.length];

export const AXIS_TICK = { fontSize: 11, fill: "var(--text-muted)" };
export const GRID_STROKE = "var(--border)";

export const TOOLTIP_STYLE: CSSProperties = {
  background: "var(--elevated)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  fontSize: 12,
  color: "var(--text)",
};
