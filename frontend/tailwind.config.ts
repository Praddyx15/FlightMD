import type { Config } from "tailwindcss";
import plugin from "tailwindcss/plugin";
import tokens from "./design/tokens.json";

// colours resolve to the CSS variables that scripts/tokens-to-css.mjs writes from
// design/tokens.json; the -rgb form keeps bg-x/15 working
const token = (name: string) => `rgb(var(--${name}-rgb) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        elevated: token("elevated"),
        border: token("border"),
        fg: {
          DEFAULT: token("text"),
          muted: token("text-muted"),
          subtle: token("text-subtle"),
        },
        accent: {
          DEFAULT: token("accent"),
          solid: token("accent-solid"),
          text: token("accent-text"),
        },
        "on-accent": token("on-accent"),
        critical: { DEFAULT: token("critical"), fill: token("critical-fill") },
        caution: { DEFAULT: token("caution"), fill: token("caution-fill") },
        advisory: { DEFAULT: token("advisory"), fill: token("advisory-fill") },
        ok: { DEFAULT: token("ok"), fill: token("ok-fill") },
        sim: token("sim"),
      },
      borderColor: {
        DEFAULT: token("border"),
      },
      borderRadius: {
        DEFAULT: `${tokens.radius.web}px`,
        sm: `${tokens.radius.web - 2}px`,
        md: `${tokens.radius.web}px`,
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      // the suite type scale: 11/16, 12/18, 14/20, 16/24, 22/28, 32/36
      fontSize: {
        "2xs": ["11px", { lineHeight: "16px" }],
        xs: ["12px", { lineHeight: "18px" }],
        sm: ["14px", { lineHeight: "20px" }],
        base: ["16px", { lineHeight: "24px" }],
        value: ["22px", { lineHeight: "28px" }],
        hero: ["32px", { lineHeight: "36px" }],
      },
      transitionDuration: {
        DEFAULT: "150ms",
      },
    },
  },
  plugins: [
    plugin(({ addVariant }) => {
      // gloves on a tablet: targets go to 44 px
      addVariant("pointer-coarse", "@media (pointer: coarse)");
      addVariant("reduce-motion", "@media (prefers-reduced-motion: reduce)");
    }),
  ],
};

export default config;
