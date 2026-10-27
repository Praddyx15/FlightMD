// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import tokens from "@/design/tokens.json";

// WCAG 2.x relative luminance and contrast ratio
function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

type Theme = typeof tokens.themes.dark;
const THEMES = Object.entries(tokens.themes) as [string, Theme][];
const GROUNDS = ["bg0", "bg1", "bg2"] as const;
type Ground = (typeof GROUNDS)[number];

describe("contrast", () => {
  it("knows the WCAG reference values", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
  });

  describe.each(THEMES)("%s theme", (_: string, theme: Theme) => {
    it.each(GROUNDS)("body text reaches 4.5:1 on %s", (ground: Ground) => {
      for (const fg of ["fg0", "fg1", "accentText"] as const) {
        expect(contrast(theme[fg], theme[ground]), `${fg} on ${ground}`).toBeGreaterThanOrEqual(4.5);
      }
    });

    it.each(GROUNDS)("alert text reaches 7:1 on %s", (ground: Ground) => {
      expect(contrast(theme.warnRedText, theme[ground])).toBeGreaterThanOrEqual(7);
    });

    // caution, advisory and ok always come with an icon and a word, so 4.5:1 is the bar
    it.each(GROUNDS)("status text reaches 4.5:1 on %s", (ground: Ground) => {
      for (const fg of ["cautionAmber", "advisoryCyan", "okGreen"] as const) {
        expect(contrast(theme[fg], theme[ground]), `${fg} on ${ground}`).toBeGreaterThanOrEqual(4.5);
      }
    });
  });
});

describe("app/tokens.css", () => {
  it("is generated from the current tokens.json", () => {
    const css = readFileSync(fileURLToPath(new URL("../app/tokens.css", import.meta.url)), "utf8");
    const [dark, light] = css.split(".light {");
    expect(dark).toContain(`--critical: ${tokens.themes.dark.warnRedText.toLowerCase()};`);
    expect(dark).toContain(`--bg: ${tokens.themes.dark.bg0.toLowerCase()};`);
    expect(dark).toContain(`--critical-fill: ${tokens.themes.dark.warnRed.toLowerCase()};`);
    expect(light).toContain(`--critical: ${tokens.themes.light.warnRedText.toLowerCase()};`);
    expect(light).toContain(`--text-muted: ${tokens.themes.light.fg1.toLowerCase()};`);
  });
});
