import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg:            "var(--bg-primary)",
        card:          "var(--bg-card)",
        elevated:      "var(--bg-elevated)",
        surface:       "var(--surface)",
        "surface-2":   "var(--surface-2)",
        accent:        "var(--accent)",
        border:        "var(--border)",
        "text-secondary": "var(--text-secondary)",
        "text-muted":  "var(--text-muted)",
        gold: {
          DEFAULT: "#B89642",
          50:  "#F7F0DE",
          100: "#EFE1BE",
          200: "#E7C25B",
          300: "#D1AE52",
          400: "#C7A44B",
          500: "#B89642",
          600: "#9C7F37",
          700: "#6F5820",
          800: "#4A3B15",
          900: "#2A2418",
        },
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "JetBrains Mono", "Fira Code", "Cascadia Code", "Consolas", "monospace"],
        display: ["var(--font-display)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
