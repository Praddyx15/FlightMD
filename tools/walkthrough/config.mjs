/**
 * Render settings. Environment variables override the ones marked "env".
 */

import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const env = process.env;

function number(name, fallback) {
  const value = Number.parseFloat(env[name] ?? "");
  return Number.isFinite(value) ? value : fallback;
}

export const CONFIG = {
  // env: where the running app is (README.md, "Start FlightMD")
  appUrl: env.APP_URL || "http://localhost:3000",
  apiUrl: env.API_URL || "http://localhost:8000",

  // Browser: a 1536×864 layout rendered at 1.25× gives 1920×1080 frames with UI text 25 % larger
  // than a plain 1080p screen recording.
  viewport: { width: 1536, height: 864 },
  deviceScaleFactor: 1.25,
  output: { width: 1920, height: 1080, fps: 30 },
  jpegQuality: 92,
  // env HEADLESS=1: no window. Fine for FlightMD's charts, but check the review frames.
  // OFFSCREEN=1: a real window placed off the screen, so it does not cover your desktop.
  headless: env.HEADLESS === "1",
  offscreen: env.OFFSCREEN === "1",
  settleMs: 600,
  // --stills: plain 1536×864 screenshots for docs/walkthrough/
  stillsScale: 1,
  stillsDir: path.resolve(here, "..", "..", "docs", "walkthrough"),

  // The logs the scenes upload, through the page like a user would (synthetic, see its README)
  logsDir: path.resolve(here, "..", "..", "tests", "sample_logs"),
  // each render tags its flights with the first free "Quad-N" on the API
  airframeBase: "Quad",

  // Voice: Kokoro-82M through kokoro-js (Apache-2.0), on the CPU
  voice: env.VOICE || "af_heart", // env; e.g. af_bella, am_michael, bf_emma, bm_george
  voiceSpeed: number("VOICE_SPEED", 1.0), // env
  voiceModel: "onnx-community/Kokoro-82M-v1.0-ONNX",
  // a Hugging Face commit, so the weights can't change under us (README: "Model revision")
  voiceRevision: "1939ad2a8e416c0acfeecc08a694d14ef25f2231",
  voiceDtype: "q8",

  // Timing (seconds)
  leadSeconds: 0.35, // the voice starts this long after the picture
  tailSeconds: 1.0, // the picture holds this long after the voice
  finalHoldSeconds: 1.6, // ...and at least this long after the scene's last visible action
  crossfadeSeconds: 0.45,
  transition: "fade", // ffmpeg xfade transition
  fastFactor: 4, // waits play this many times faster

  // Sound
  clickGain: 0.35,
  whooshGain: 0.18,
  musicGainDb: number("MUSIC_DB", -21), // env; music level before ducking, relative
  duck: { threshold: 0.025, ratio: 6, attackMs: 20, releaseMs: 400 },
  loudness: { I: -16, TP: -1.5, LRA: 11 },

  // End card
  repoUrl: env.REPO_URL || "https://github.com/Praddyx15/FlightMD", // env; same link as the app's header

  // Brand colours (frontend/design/tokens.json, dark theme)
  colors: {
    bg: "#0b0e11",
    surface: "#12161b",
    border: "#2a323c",
    text: "#e6eaee",
    textMuted: "#9aa5b1",
    accent: "#3b82f6",
    accentSolid: "#2563eb",
    accentText: "#60a5fa",
    warn: "#f5a524",
  },

  // Target length of the finished walkthrough (checked by verify.mjs)
  minSeconds: 120,
  maxSeconds: 180,

  // --story teaser (teaser.mjs): these replace the settings above
  teaser: {
    minSeconds: 30,
    maxSeconds: 40,
    tailSeconds: 0.6,
  },

  outDir: path.join(here, "out"),
  workDir: path.join(here, "out", "work"),
  cacheDir: path.join(here, "out", "cache", "voice"),
};

/** The settings for one story: the walkthrough uses CONFIG as it is. */
export function configFor(story) {
  return story === "teaser" ? { ...CONFIG, ...CONFIG.teaser } : CONFIG;
}
