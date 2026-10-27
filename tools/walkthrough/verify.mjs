#!/usr/bin/env node
/**
 * Check a rendered video with numbers, and extract frames to look at.
 *
 *   node verify.mjs                     checks out/walkthrough.mp4
 *   node verify.mjs teaser              checks out/teaser.mp4
 *   node verify.mjs walkthrough-draft   checks a draft (picture only)
 *
 * Checks: 1920×1080, 30 fps, H.264 + AAC; length within the story's target; integrated loudness
 * and true peak; every voice line starts within 0.2 s of its first caption; no error text was on
 * screen. Frames from the middle and end of every scene and just after every click are written to
 * out/review/<name>/ for a person to look at. Nothing here can judge how the audio sounds:
 * listen once before sharing.
 */

import { existsSync } from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { CONFIG, configFor } from "./config.mjs";
import { ffmpeg, measureLoudness, num, probe } from "./lib/ffmpeg.mjs";

// error states from frontend/messages/en.json
const ERROR_TEXT = [
  "Something went wrong",
  "Something broke on this page",
  "Analysis failed",
  "Report expired",
  "Can't reach the server",
  "Network error",
  "Server busy",
  "Upload limit reached",
  "could not be drawn",
  "could not be displayed",
  // not a bare "could not": finding text can say that about a flight
  "Could not load",
  "Could not compare",
  "Could not record",
];

async function speechStarts(file) {
  const { stderr } = await ffmpeg(["-i", file, "-af", "silencedetect=noise=-40dB:d=0.25", "-f", "null", "-"]);
  return [...stderr.matchAll(/silence_end:\s*([\d.]+)/g)].map((m) => Number.parseFloat(m[1]));
}

async function main() {
  const name = process.argv[2] ?? "walkthrough";
  const out = CONFIG.outDir;
  const file = path.join(out, `${name}.mp4`);
  const manifestFile = path.join(out, `${name}.manifest.json`);
  if (!existsSync(file) || !existsSync(manifestFile)) throw new Error(`Render first: ${file} or its manifest is missing.`);
  const manifest = JSON.parse(await readFile(manifestFile, "utf8"));
  const checks = [];
  const check = (label, pass, value, expected) => checks.push({ label, pass: Boolean(pass), value, expected });

  const info = await probe(file);
  const video = info.streams.find((s) => s.codec_type === "video");
  const audio = info.streams.find((s) => s.codec_type === "audio");
  const duration = Number.parseFloat(info.format.duration);
  const { width, height, fps } = CONFIG.output;
  check("Video codec", video?.codec_name === "h264", video?.codec_name ?? "none", "h264");
  check("Resolution", video?.width === width && video?.height === height, `${video?.width}x${video?.height}`, `${width}x${height}`);
  check("Frame rate", video?.r_frame_rate === `${fps}/1`, video?.r_frame_rate, `${fps}/1`);
  check("Pixel format", video?.pix_fmt === "yuv420p", video?.pix_fmt, "yuv420p");
  if (name === "walkthrough" || name === "teaser") {
    const { minSeconds, maxSeconds } = configFor(name);
    check("Length", duration >= minSeconds && duration <= maxSeconds, `${duration.toFixed(1)} s`, `${minSeconds}–${maxSeconds} s`);
  }

  if (!manifest.draft) {
    check("Audio codec", audio?.codec_name === "aac", audio?.codec_name ?? "none", "aac");
    check("Audio format", audio?.sample_rate === "48000" && audio?.channels === 2, `${audio?.sample_rate} Hz, ${audio?.channels} ch`, "48000 Hz, 2 ch");
    const target = CONFIG.loudness;
    const loud = await measureLoudness(file, target);
    check("Integrated loudness", Math.abs(loud.input_i - target.I) <= 1, `${loud.input_i.toFixed(1)} LUFS`, `${target.I} ±1 LUFS`);
    check("True peak", loud.input_tp <= target.TP + 0.5, `${loud.input_tp.toFixed(1)} dBTP`, `≤ ${target.TP + 0.5} dBTP`);

    const voiceFile = path.join(CONFIG.workDir, `${name}-voice.wav`);
    if (existsSync(voiceFile)) {
      const starts = await speechStarts(voiceFile);
      for (const scene of manifest.scenes) {
        const expected = scene.start + manifest.leadSeconds;
        const nearest = starts.reduce((best, t) => (Math.abs(t - expected) < Math.abs(best - expected) ? t : best), Number.POSITIVE_INFINITY);
        const diff = nearest - expected;
        check(`Voice timing: ${scene.id}`, Math.abs(diff) <= 0.2, Number.isFinite(diff) ? `${diff >= 0 ? "+" : ""}${diff.toFixed(2)} s` : "no speech found", "within ±0.20 s of the caption");
      }
    } else {
      check("Voice timing", false, `out/work/${name}-voice.wav missing`, "verify a render made in this folder");
    }
  }

  for (const scene of manifest.scenes) {
    const cue = manifest.cues.find((c) => c.scene === scene.id);
    check(`Caption: ${scene.id}`, Boolean(cue), cue ? `${cue.text.slice(0, 48)}…` : "none", "a caption cue");
  }

  const seenFile = path.join(out, `${name}.seen.json`);
  if (existsSync(seenFile)) {
    const seen = JSON.parse(await readFile(seenFile, "utf8"));
    for (const [scene, text] of Object.entries(seen)) {
      const hits = ERROR_TEXT.filter((needle) => text.toLowerCase().includes(needle.toLowerCase()));
      check(`No error text: ${scene}`, hits.length === 0, hits.length ? hits.join(", ") : "none", "none");
    }
  }

  // one folder per video, so the walkthrough's frames survive a teaser check
  const reviewDir = path.join(out, "review", name);
  await rm(reviewDir, { recursive: true, force: true });
  await mkdir(reviewDir, { recursive: true });
  const shots = [];
  manifest.scenes.forEach((scene, i) => {
    const tag = `${String(i + 1).padStart(2, "0")}-${scene.id}`;
    shots.push({ at: scene.start + scene.duration * 0.5, file: `${tag}-mid.jpg` });
    shots.push({ at: scene.start + Math.max(0.1, scene.duration - 0.6), file: `${tag}-end.jpg` });
    scene.clicks.forEach((t, k) => shots.push({ at: t + 0.12, file: `${tag}-click${k + 1}.jpg` }));
  });
  for (const shot of shots) {
    const at = Math.min(Math.max(0, shot.at), Math.max(0, duration - 0.05));
    await ffmpeg(["-ss", num(at), "-i", file, "-frames:v", "1", "-q:v", "3", path.join(reviewDir, shot.file)]);
  }

  const failed = checks.filter((c) => !c.pass);
  const labelWidth = Math.max(...checks.map((c) => c.label.length));
  for (const c of checks) console.log(`${c.pass ? "PASS" : "FAIL"}  ${c.label.padEnd(labelWidth)}  ${c.value}  (expected ${c.expected})`);
  console.log(`\n${shots.length} review frames in ${reviewDir}`);
  console.log("Not checked: how the voice and music sound. Listen once, with headphones, before sharing.");
  await writeFile(path.join(out, `${name}.verify.json`), JSON.stringify({ file, checked: new Date().toISOString(), checks, reviewFrames: shots }, null, 2));
  if (failed.length) {
    console.log(`\n${failed.length} check(s) failed.`);
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(`\n${error.message}`);
  process.exit(1);
});
