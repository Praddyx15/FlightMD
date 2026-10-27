#!/usr/bin/env node
/**
 * Render the FlightMD walkthrough (or the teaser) from the running app.
 *
 *   node record.mjs                   full render: voice, music, out/walkthrough.mp4 (+ .vtt, thumbnail, manifest)
 *   node record.mjs --story teaser    the 30–40 s cut (teaser.mjs), out/teaser.mp4
 *   node record.mjs --draft           no voice or audio; line lengths estimated; out/<story>-draft.mp4
 *   node record.mjs --only params     one scene (or several: --only verdict,params); out/scene-<ids>.mp4.
 *                                     Earlier scenes still run, unfilmed, to get the app to that point.
 *   node record.mjs --stills          no video: screenshots for docs/WALKTHROUGH.md into docs/walkthrough/
 *   node record.mjs --no-music        voice and clicks only
 *   node record.mjs --music bed.mp3   your own track (looped, faded, lowered under the voice)
 *
 * Needs: the API and web app running (README.md, "Start FlightMD"), ffmpeg on PATH, and the
 * packages from `npm install` + `npm run setup`. See README.md.
 */

import { existsSync, readFileSync } from "node:fs";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";
import { configFor } from "./config.mjs";
import { buildScenes as walkthroughScenes } from "./scenes.mjs";
import { buildScenes as teaserScenes } from "./teaser.mjs";
import { freeLabel, preflight } from "./lib/app.mjs";
import { assemble } from "./lib/assemble.mjs";
import { encodeClip } from "./lib/capture.mjs";
import { ffmpegMajorVersion, hasEncoder, hasFilter } from "./lib/ffmpeg.mjs";
import { installOverlay } from "./lib/overlay.mjs";
import { Stage } from "./lib/stage.mjs";
import { synthesizeAll } from "./lib/tts.mjs";

const STORIES = { walkthrough: walkthroughScenes, teaser: teaserScenes };

function parseArgs(argv) {
  const args = { story: "walkthrough", draft: false, stills: false, only: null, music: undefined };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--draft") args.draft = true;
    else if (arg === "--stills") args.stills = true;
    else if (arg === "--no-music") args.music = false;
    else if (arg === "--music") args.music = argv[++i] ?? "";
    else if (arg.startsWith("--music=")) args.music = arg.slice("--music=".length);
    else if (arg === "--only") args.only = argv[++i];
    else if (arg.startsWith("--only=")) args.only = arg.slice("--only=".length);
    else if (arg === "--story") args.story = argv[++i];
    else if (arg.startsWith("--story=")) args.story = arg.slice("--story=".length);
    else if (arg === "--help" || arg === "-h") args.help = true;
    else throw new Error(`Unknown argument: ${arg} (try --help)`);
  }
  if (args.music === "") throw new Error("--music needs a file path");
  if (args.only === "" || args.only === undefined) throw new Error("--only needs one or more scene ids");
  if (!STORIES[args.story]) throw new Error(`Unknown story "${args.story}". Known: ${Object.keys(STORIES).join(", ")}`);
  if (args.stills && args.story !== "walkthrough") throw new Error("--stills belongs to the walkthrough story");
  return args;
}

const started = Date.now();
const log = (message) => console.log(`[${((Date.now() - started) / 1000).toFixed(1).padStart(6)} s] ${message}`);

async function checkTools() {
  const major = await ffmpegMajorVersion();
  if (major !== null && major < 5) throw new Error(`ffmpeg ${major}.x is too old; install ffmpeg 5 or newer.`);
  for (const filter of ["xfade", "loudnorm", "sidechaincompress", "amix"]) {
    if (!(await hasFilter(filter))) throw new Error(`This ffmpeg build has no '${filter}' filter; install a full build (see README.md).`);
  }
  for (const encoder of ["libx264", "aac"]) {
    if (!(await hasEncoder(encoder))) throw new Error(`This ffmpeg build has no '${encoder}' encoder; install a full build (see README.md).`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(readFileSync(new URL(import.meta.url), "utf8").split("*/")[0]);
    return;
  }
  if (typeof args.music === "string" && !existsSync(args.music)) throw new Error(`Music file not found: ${args.music}`);
  const config = configFor(args.story);

  log(args.stills ? "Checking the running app" : "Checking ffmpeg and the running app");
  if (!args.stills) await checkTools();
  const health = await preflight(config, log);
  const label = await freeLabel(config.apiUrl, config.airframeBase);
  log(`API ${health.version}, report schema ${health.schema_version}; flights tagged "${label}"`);

  const repo = config.repoUrl.replace(/^https?:\/\//, "").replace(/\/+$/, "");
  let scenes = STORIES[args.story]({ cta: repo || "Free on GitHub · MIT licence", label, logsDir: config.logsDir });
  let wanted = null;
  if (args.only) {
    wanted = new Set(args.only.split(",").map((x) => x.trim()).filter(Boolean));
    const unknown = [...wanted].filter((id) => !scenes.some((s) => s.id === id));
    if (unknown.length) throw new Error(`Unknown scene id(s): ${unknown.join(", ")}. Known: ${scenes.map((s) => s.id).join(", ")}`);
    // nothing after the last wanted scene needs to run
    const last = Math.max(...scenes.map((s, i) => (wanted.has(s.id) ? i : -1)));
    scenes = scenes.slice(0, last + 1);
  }
  const filmed = args.stills ? [] : scenes.filter((s) => !wanted || wanted.has(s.id));
  const name = args.only ? `scene-${filmed.map((s) => s.id).join("+")}` : args.draft ? `${args.story}-draft` : args.story;

  await mkdir(config.outDir, { recursive: true });
  // Fresh frames and clips; other renders' voice tracks (work/<name>-voice.wav) stay for verify.
  await rm(path.join(config.workDir, "frames"), { recursive: true, force: true });
  await rm(path.join(config.workDir, "clips"), { recursive: true, force: true });
  await mkdir(path.join(config.workDir, "clips"), { recursive: true });
  if (args.stills) await mkdir(config.stillsDir, { recursive: true });

  let voices = new Map();
  if (!args.stills) {
    log(args.draft ? "Draft: estimating line lengths (no voice)" : `Voice: Kokoro '${config.voice}'`);
    voices = await synthesizeAll(filmed, {
      voice: config.voice,
      speed: config.voiceSpeed,
      model: config.voiceModel,
      revision: config.voiceRevision,
      dtype: config.voiceDtype,
      cacheDir: config.cacheDir,
      draft: args.draft,
      log,
    });
  }

  const headless = config.headless || args.stills;
  const browser = await chromium.launch({
    headless,
    args: [
      "--hide-scrollbars",
      "--force-color-profile=srgb",
      // A real window off the visible screen; keep painting although nobody can see it.
      ...(!headless && config.offscreen
        ? ["--window-position=-4000,0", "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding"]
        : []),
    ],
  });
  const context = await browser.newContext({
    viewport: config.viewport,
    deviceScaleFactor: args.stills ? config.stillsScale : config.deviceScaleFactor,
    colorScheme: "dark",
    reducedMotion: "no-preference",
    locale: "en-GB",
    permissions: ["clipboard-read", "clipboard-write"], // "Copy all" on the parameter sheet
  });
  await context.addInitScript(() => {
    // the native print dialog would block the page; the export scene emulates print media instead
    window.print = () => {};
    try {
      // dark theme and metric units to start with; a scene that changes them keeps its choice
      if (!localStorage.getItem("flightmd.theme")) localStorage.setItem("flightmd.theme", "dark");
      if (!localStorage.getItem("flightmd.units")) localStorage.setItem("flightmd.units", JSON.stringify("metric"));
    } catch {
      // storage blocked: the app falls back to its defaults (dark from colorScheme, metric)
    }
  });
  if (!args.stills) {
    await context.addInitScript(installOverlay, {
      width: config.viewport.width,
      height: config.viewport.height,
      colors: config.colors,
    });
  }
  const page = await context.newPage();
  page.setDefaultTimeout(60_000);
  const stage = new Stage({ page, config, workDir: config.workDir, log, stillsDir: args.stills ? config.stillsDir : null });

  const takes = [];
  const seen = {};
  const ids = {};
  try {
    for (const [index, scene] of scenes.entries()) {
      const film = filmed.includes(scene);
      const ctx = { s: stage, page, ids };
      log(`Scene ${index + 1}/${scenes.length}: ${scene.id}${film ? "" : " (not filmed)"}`);
      stage.filming = film;
      await stage.reset();
      if (scene.prepare) await scene.prepare(ctx);
      if (!film) {
        await scene.run(ctx);
        continue;
      }
      const voice = voices.get(scene.id);
      await stage.begin(scene, voice, index);
      await scene.run(ctx);
      const take = await stage.end();
      seen[scene.id] = await page.evaluate(() => document.body.innerText.slice(0, 20000)).catch(() => "");
      log(`  ${take.duration.toFixed(2)} s, ${take.frames.length} frames, ${take.clicks.length} click(s)`);
      takes.push({ scene, index, voice, take });
    }
  } catch (error) {
    const shot = path.join(config.outDir, "failed.png");
    await page.screenshot({ path: shot }).catch(() => {});
    await browser.close().catch(() => {});
    error.message += `\nA screenshot of the page at the failure is in ${shot}.`;
    throw error;
  }
  await browser.close();

  if (args.stills) {
    log(`Done: stills in ${config.stillsDir}`);
    return;
  }

  // encoded after recording, so the app keeps going between scenes w/o a pause
  log("Encoding the scene clips");
  const results = [];
  for (const { scene, index, voice, take } of takes) {
    const clip = path.join(config.workDir, "clips", `${String(index + 1).padStart(2, "0")}-${scene.id}.mp4`);
    await encodeClip({
      frames: take.frames,
      dir: take.frameDir,
      mapTime: take.mapTime,
      duration: take.duration,
      fps: config.output.fps,
      width: config.output.width,
      height: config.output.height,
      file: clip,
    });
    results.push({ id: scene.id, say: scene.say, thumbnail: Boolean(scene.thumbnail), clip, duration: take.duration, voice, clicks: take.clicks, cues: take.cues });
  }

  const music = args.draft ? false : args.music;
  const output = await assemble({ scenes: results, config, outDir: config.outDir, workDir: config.workDir, draft: args.draft, music, name, log });
  await writeFile(path.join(config.outDir, `${name}.seen.json`), JSON.stringify(seen, null, 2));

  log(`Done: ${output.file} (${output.total.toFixed(1)} s)`);
  console.log(`  captions   ${output.vttFile}`);
  console.log(`  thumbnail  ${output.thumbnail}`);
  console.log(`  manifest   ${output.manifestFile}`);
  if (!args.draft) {
    console.log(`Next: npm run verify -- ${name}, then watch it once with the sound on and once muted before sharing.`);
  }
}

main().catch((error) => {
  console.error(`\n${error.message}`);
  process.exit(1);
});
