/**
 * Frame capture through the DevTools screencast (what Playwright's own video uses, but at full
 * quality), and the captured frames turned into a constant-frame-rate clip.
 *
 * Chrome only sends a frame when the page repaints, so each frame is shown until the next one
 * (an ffconcat list with per-frame durations), on the output clock so sped-up waits play faster.
 */

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { ffmpeg, num } from "./ffmpeg.mjs";

export class ScreencastRecorder {
  /**
   * @param {import('playwright').Page} page
   * @param {{ dir: string, width: number, height: number, quality?: number }} options
   */
  constructor(page, { dir, width, height, quality = 92 }) {
    this.page = page;
    this.dir = dir;
    this.width = width;
    this.height = height;
    this.quality = quality;
    this.frames = [];
    this.writes = [];
    this.session = null;
    this.onFrame = this.onFrame.bind(this);
  }

  async start() {
    await mkdir(this.dir, { recursive: true });
    this.frames = [];
    this.writes = [];
    this.session = await this.page.context().newCDPSession(this.page);
    this.session.on("Page.screencastFrame", this.onFrame);
    await this.session.send("Page.startScreencast", {
      format: "jpeg",
      quality: this.quality,
      maxWidth: this.width,
      maxHeight: this.height,
      everyNthFrame: 1,
    });
  }

  onFrame(event) {
    const received = Date.now() / 1000;
    const stamp = event.metadata?.timestamp;
    if (process.env.FMD_DEBUG_TIMING) (this.debug ??= []).push(received - (typeof stamp === "number" ? stamp : received));
    // The frame's own timestamp is wall-clock seconds (when it was painted; it can arrive seconds
    // later with software rendering). Fall back to arrival time if it is missing or implausible.
    const usable = typeof stamp === "number" && stamp <= received + 1 && received - stamp < 30;
    if (!usable) this.fallbacks = (this.fallbacks ?? 0) + 1;
    const ts = usable ? stamp : received;
    const name = `f${String(this.frames.length).padStart(6, "0")}.jpg`;
    this.frames.push({ ts, name });
    this.writes.push(writeFile(path.join(this.dir, name), Buffer.from(event.data, "base64")));
    this.session?.send("Page.screencastFrameAck", { sessionId: event.sessionId }).catch(() => {});
  }

  /**
   * Wait for a frame painted at or after `realTime` (epoch seconds); false after `timeoutMs`.
   * The overlay's `tick()` forces a repaint, so a frame comes even when nothing on screen changes.
   */
  async drain(realTime, timeoutMs = 6000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const last = this.frames[this.frames.length - 1];
      if (last && last.ts >= realTime) return true;
      await this.page.evaluate(() => window.__fmd?.tick()).catch(() => {});
      await new Promise((resolve) => setTimeout(resolve, 60));
    }
    return false;
  }

  /** Stop capturing; resolves with the frames ({ ts, name }) once all are written. */
  async stop() {
    const session = this.session;
    this.session = null;
    if (session) {
      await session.send("Page.stopScreencast").catch(() => {});
      session.off("Page.screencastFrame", this.onFrame);
      await session.detach().catch(() => {});
    }
    await Promise.all(this.writes);
    if (process.env.FMD_DEBUG_TIMING && this.fallbacks) console.log(`  timing: ${this.fallbacks} frame(s) without a usable timestamp`);
    this.fallbacks = 0;
    if (this.debug?.length) {
      const d = [...this.debug].sort((a, b) => a - b);
      console.log(`  timing: arrival - stamp median ${d[d.length >> 1].toFixed(3)} s, min ${d[0].toFixed(3)}, max ${d[d.length - 1].toFixed(3)} (${d.length} frames)`);
      this.debug = [];
    }
    return this.frames;
  }
}

/**
 * Encode captured frames as an H.264 clip of exactly `duration` output seconds at `fps`.
 * `mapTime(ts)` converts a frame's wall-clock timestamp to output seconds from the clip start.
 */
export async function encodeClip({ frames, dir, mapTime, duration, fps, width, height, file }) {
  if (frames.length === 0) throw new Error("No frames were captured. Keep the browser window visible while recording.");
  // Chrome can send ~60 frames/s: keep at most one picture per output frame slot, so every
  // entry's duration is its real on-screen time (never padded, which would stretch the clip).
  const minStep = 1 / fps;
  // frames can arrive out of paint order under load
  const timed = frames
    .map((frame, order) => ({ name: frame.name, order, at: Math.max(0, mapTime(frame.ts)) }))
    .sort((a, b) => a.at - b.at || a.order - b.order);
  const entries = [];
  for (const frame of timed) {
    const last = entries[entries.length - 1];
    if (last && frame.at >= duration - minStep) continue; // painted after the scene ended
    if (last && frame.at - last.at < minStep) {
      last.name = frame.name; // a newer picture for (almost) the same instant
      continue;
    }
    entries.push({ name: frame.name, at: entries.length === 0 ? 0 : frame.at });
  }
  const lines = ["ffconcat version 1.0"];
  for (let i = 0; i < entries.length; i++) {
    const end = i + 1 < entries.length ? entries[i + 1].at : duration;
    const length = Math.max(0.001, end - entries[i].at);
    lines.push(`file '${entries[i].name}'`, `duration ${num(length, 6)}`);
  }
  lines.push(`file '${entries[entries.length - 1].name}'`); // the concat demuxer needs the last file twice
  const list = path.join(dir, "frames.ffconcat");
  await writeFile(list, `${lines.join("\n")}\n`);

  await ffmpeg([
    "-f", "concat",
    "-safe", "0",
    "-i", list,
    // Screencast JPEGs are full-range sRGB: convert to the TV-range BT.709 players expect.
    "-vf", `scale=${width}:${height}:flags=lanczos:in_range=pc:out_range=tv,fps=${fps},format=yuv420p`,
    "-color_range", "tv",
    "-colorspace", "bt709",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
    "-t", num(duration, 4),
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "14",
    "-r", String(fps),
    "-an",
    file,
  ]);
}
