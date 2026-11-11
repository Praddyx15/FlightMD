/**
 * Thin wrappers around the ffmpeg and ffprobe command-line tools (they must be on PATH).
 * Arguments are passed as an array (no shell), so filter graphs need no shell quoting.
 */

import { spawn } from "node:child_process";

/** Run a command; resolve with its output, reject with the tail of stderr on a non-zero exit. */
export function run(command, args, { cwd } = {}) {
  return new Promise((resolve, reject) => {
    let child;
    try {
      child = spawn(command, args, { cwd, windowsHide: true });
    } catch (error) {
      reject(error);
      return;
    }
    const out = [];
    const err = [];
    child.stdout.on("data", (chunk) => out.push(chunk));
    child.stderr.on("data", (chunk) => err.push(chunk));
    child.on("error", (error) => {
      if (error.code === "ENOENT") {
        reject(new Error(`'${command}' was not found on PATH. Install it (see tools/walkthrough/README.md) and open a new terminal.`));
      } else {
        reject(error);
      }
    });
    child.on("close", (code) => {
      const stdout = Buffer.concat(out).toString("utf8");
      const stderr = Buffer.concat(err).toString("utf8");
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${command} exited with code ${code}:\n${stderr.slice(-3000)}`));
    });
  });
}

export function ffmpeg(args, options) {
  return run("ffmpeg", ["-hide_banner", "-nostdin", "-y", ...args], options);
}

export function ffprobe(args, options) {
  return run("ffprobe", ["-v", "error", ...args], options);
}

/** Major version of the installed ffmpeg, or null for builds that do not say (git snapshots). */
export async function ffmpegMajorVersion() {
  const { stdout } = await run("ffmpeg", ["-hide_banner", "-version"]);
  const match = stdout.match(/ffmpeg version n?(\d+)\.(\d+)/);
  return match ? Number(match[1]) : null;
}

export async function hasFilter(name) {
  const { stdout } = await run("ffmpeg", ["-hide_banner", "-filters"]);
  return new RegExp(`\\s${name}\\s`).test(stdout);
}

export async function hasEncoder(name) {
  const { stdout } = await run("ffmpeg", ["-hide_banner", "-encoders"]);
  return new RegExp(`\\s${name}\\s`).test(stdout);
}

/** Duration of a media file in seconds. */
export async function probeDuration(file) {
  const { stdout } = await ffprobe(["-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file]);
  const seconds = Number.parseFloat(stdout.trim());
  if (!Number.isFinite(seconds)) throw new Error(`Could not read the duration of ${file}`);
  return seconds;
}

/** Streams and format of a media file (ffprobe JSON). */
export async function probe(file) {
  const { stdout } = await ffprobe([
    "-show_entries",
    "stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,pix_fmt,sample_rate,channels:format=duration,bit_rate",
    "-of",
    "json",
    file,
  ]);
  return JSON.parse(stdout);
}

/**
 * Measure loudness with the loudnorm filter (EBU R128). Returns the parsed JSON block:
 * input_i (LUFS), input_tp (dBTP), input_lra, input_thresh, target_offset.
 */
export async function measureLoudness(file, { I = -16, TP = -1.5, LRA = 11 } = {}) {
  const { stderr } = await ffmpeg(["-i", file, "-af", `loudnorm=I=${I}:TP=${TP}:LRA=${LRA}:print_format=json`, "-vn", "-f", "null", "-"]);
  const start = stderr.lastIndexOf("{");
  const end = stderr.lastIndexOf("}");
  if (start < 0 || end < start) throw new Error("loudnorm printed no measurement");
  const data = JSON.parse(stderr.slice(start, end + 1));
  for (const key of ["input_i", "input_tp", "input_lra", "input_thresh", "target_offset"]) {
    const value = Number.parseFloat(data[key]);
    if (!Number.isFinite(value)) throw new Error(`loudnorm measurement has no usable ${key} (is the audio silent?)`);
    data[key] = value;
  }
  return data;
}

/** Seconds to "HH:MM:SS.mmm" (WebVTT). */
export function vttTime(seconds) {
  const ms = Math.max(0, Math.round(seconds * 1000));
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  const rest = ms % 1000;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(rest).padStart(3, "0")}`;
}

/** Number formatted for an ffmpeg argument (fixed decimals, no exponent). */
export function num(value, decimals = 3) {
  return Number(value).toFixed(decimals);
}
