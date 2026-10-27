/**
 * The stage: what a scene script uses to act on the app while it is being recorded.
 *
 * Time: every scene has an *output* clock (seconds into the finished clip). It equals real time
 * except inside `waitFor(..., { speedUp: true })`, where it runs `fastFactor` times slower than
 * real time, so a wait for an analysis plays back sped up. Captions, clicks and the end of the
 * scene are all placed on the output clock, which keeps them in sync with the voice.
 *
 * Scene scripts (scenes.mjs, teaser.mjs) receive `{ s, page, ids }`:
 *   s.goto(path, readyLocator)   load a page (use in `prepare`, which is not recorded)
 *   s.click(locator)             glide the pointer there, ripple, click (click sound in the mix)
 *   s.type(locator, text)        click into a field and type, key by key
 *   s.choose(locator, value)     pick an option in a <select> without opening its native popup
 *   s.pickFile(locator, file)    click something that opens the file chooser and answer it
 *   s.waitFor(locator)           wait for a real page state; long waits play sped up with a badge
 *   s.waitFor(async () => bool)  the same for a state no single locator shows (polled)
 *   s.spotlight(locator, label)  dim everything else, ring the target, add a callout label
 *   s.clearSpotlight()
 *   s.card(spec) / s.list(spec)  full-screen title card / list of points
 *   s.hold(seconds)              let the picture breathe (output seconds)
 *   s.still(name)                --stills: save the page as docs/walkthrough/<name>.png
 *
 * A scene that isn't filmed (--stills, or one before the --only scenes) still runs, so the app
 * reaches the same state: clicks and waits happen, holds and overlay calls don't, and spotlight
 * only scrolls its target into view.
 */

import path from "node:path";
import { ScreencastRecorder } from "./capture.mjs";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Overlay calls that change what the viewer sees (the scene holds after the last of them). */
const VISIBLE_ACTIONS = new Set(["spotlight", "clearSpotlight", "ripple", "card", "closeCard", "list", "closeList"]);

/** Split a caption line into chunks of at most `maxChars`, at sentence, then comma, then word breaks. */
export function splitCaption(text, maxChars = 104) {
  const chunks = [];
  const sentences = text.trim().split(/(?<=[.!?])\s+/);
  for (const sentence of sentences) {
    if (sentence.length <= maxChars) {
      chunks.push(sentence);
      continue;
    }
    let current = "";
    for (const piece of sentence.split(/(?<=[,;:])\s+/)) {
      const candidate = current ? `${current} ${piece}` : piece;
      if (candidate.length <= maxChars) {
        current = candidate;
        continue;
      }
      if (current) chunks.push(current);
      if (piece.length <= maxChars) {
        current = piece;
        continue;
      }
      current = "";
      for (const word of piece.split(/\s+/)) {
        const next = current ? `${current} ${word}` : word;
        if (next.length > maxChars && current) {
          chunks.push(current);
          current = word;
        } else {
          current = next;
        }
      }
    }
    if (current) chunks.push(current);
  }
  // Merge short neighbours so captions do not flicker.
  const merged = [];
  for (const chunk of chunks) {
    const last = merged[merged.length - 1];
    if (last && last.length + chunk.length + 1 <= maxChars && (last.length < 40 || chunk.length < 40)) {
      merged[merged.length - 1] = `${last} ${chunk}`;
    } else {
      merged.push(chunk);
    }
  }
  return merged;
}

/** Caption cues for a scene: chunk start times spread over the voice by character count. */
export function planCaptions(text, voiceSeconds, leadSeconds) {
  const chunks = splitCaption(text);
  const total = chunks.reduce((n, c) => n + c.length, 0) || 1;
  let cumulative = 0;
  return chunks.map((chunk) => {
    const start = leadSeconds + (voiceSeconds * cumulative) / total;
    cumulative += chunk.length;
    return { text: chunk, start };
  });
}

export class Stage {
  constructor({ page, config, workDir, log, stillsDir = null }) {
    this.page = page;
    this.config = config;
    this.workDir = workDir;
    this.log = log;
    this.stillsDir = stillsDir;
    this.filming = false;
    this.clicks = [];
    this.segments = [];
    this.realStart = Date.now() / 1000;
  }

  /** Between scenes, off camera: no ring, caption or list left over from the last one. */
  async reset() {
    if (!this.filming) return;
    try {
      await this.call("clearSpotlight");
      await this.call("closeList");
      await this.call("caption", null);
      await this.call("badge", null);
    } catch {
      return; // first scene: about:blank has no overlay yet
    }
    await sleep(320); // let the fades finish before the next take starts
  }

  async begin(scene, voice, index) {
    this.scene = scene;
    this.voice = voice;
    this.clicks = [];
    this.segments = [];
    this.lastAction = 0;
    this.cues = planCaptions(scene.say, voice.duration, this.config.leadSeconds);
    this.frameDir = path.join(this.workDir, "frames", `${String(index + 1).padStart(2, "0")}-${scene.id}`);
    this.recorder = new ScreencastRecorder(this.page, {
      dir: this.frameDir,
      width: this.config.output.width,
      height: this.config.output.height,
      quality: this.config.jpegQuality,
    });
    await this.recorder.start();
    this.realStart = Date.now() / 1000;
    this.shownCaption = undefined;
    this.captionBusy = false;
    this.captionTimer = setInterval(() => this.tickCaptions(), 30);
  }

  async end() {
    const tail = this.scene.tail ?? this.config.tailSeconds;
    // Until the voice has finished (+ tail), and in any case long enough after the last action
    // for the viewer to take in its result.
    await this.holdUntil(
      Math.max(this.config.leadSeconds + this.voice.duration + tail, this.lastAction + this.config.finalHoldSeconds),
    );
    const fps = this.config.output.fps;
    const duration = Math.ceil(this.now() * fps) / fps;
    const realEnd = Date.now() / 1000;
    clearInterval(this.captionTimer);
    // Frames arrive late (seconds, with software rendering): keep recording until one painted
    // after the end has arrived, so the scene's last moments are not lost.
    if (!(await this.recorder.drain(realEnd))) this.log(`  warning: no frame after the end of "${this.scene.id}" arrived in time`);
    const frames = await this.recorder.stop();
    const realStart = this.realStart;
    if (process.env.FMD_DEBUG_TIMING) {
      const buckets = new Map();
      for (const f of frames) {
        const sec = Math.floor(f.ts - realStart);
        buckets.set(sec, (buckets.get(sec) ?? 0) + 1);
      }
      console.log(`    frames per real second: ${[...buckets.entries()].sort((a, b) => a[0] - b[0]).map(([k, v]) => `${k}:${v}`).join(" ")}; realEnd=${(realEnd - realStart).toFixed(2)}`);
    }
    const segments = this.segments.map((s) => ({ ...s, end: s.end ?? Date.now() / 1000 }));
    const mapTime = (ts) => mapOutput(ts, realStart, segments);
    const cues = this.cues
      .filter((cue) => cue.start < duration)
      .map((cue, i, list) => ({ text: cue.text, start: cue.start, end: i + 1 < list.length ? list[i + 1].start : duration }));
    return { frames, frameDir: this.frameDir, duration, mapTime, clicks: [...this.clicks], cues };
  }

  tickCaptions() {
    if (this.captionBusy) return;
    const t = this.now();
    let text = null;
    for (const cue of this.cues) if (cue.start <= t) text = cue.text;
    if (text === this.shownCaption) return;
    this.captionBusy = true;
    this.call("caption", text)
      .then(() => {
        this.shownCaption = text;
      })
      .catch(() => {})
      .finally(() => {
        this.captionBusy = false;
      });
  }

  /** Output seconds since the scene started. */
  now() {
    return mapOutput(Date.now() / 1000, this.realStart, this.segments);
  }

  async holdUntil(outputSeconds) {
    for (;;) {
      const remaining = outputSeconds - this.now();
      if (remaining <= 0) return;
      await sleep(Math.min(200, remaining * 1000));
    }
  }

  /** Keep the picture for `seconds` of output time. */
  async hold(seconds) {
    if (!this.filming) return;
    await this.holdUntil(this.now() + seconds);
  }

  async call(method, ...args) {
    if (!this.filming) return null;
    if (VISIBLE_ACTIONS.has(method)) this.lastAction = this.now();
    if (process.env.FMD_DEBUG_TIMING && method !== "caption" && method !== "tick") {
      console.log(`    t=${this.now().toFixed(2)} real=${(Date.now() / 1000 - this.realStart).toFixed(2)} ${method}`);
    }
    return this.page.evaluate(({ m, a }) => window.__fmd[m](...a), { m: method, a: args });
  }

  async box(locator, timeout = 30_000) {
    await locator.waitFor({ state: "visible", timeout });
    await locator.scrollIntoViewIfNeeded().catch(() => {});
    const b = await locator.boundingBox();
    if (!b) throw new Error(`Not on screen: ${locator}`);
    return { x: b.x, y: b.y, width: b.width, height: b.height };
  }

  /** Load an app page and wait until `ready` is visible and the network is quiet. */
  async goto(pathname, ready) {
    await this.page.goto(new URL(pathname, this.config.appUrl).toString(), { waitUntil: "domcontentloaded" });
    if (ready) await ready.waitFor({ state: "visible", timeout: 60_000 });
    await this.page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
    await this.page.evaluate(
      () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(null)))),
    );
    await sleep(this.config.settleMs);
  }

  /** Glide to the target and ripple; the time feeds the click sound. */
  async press(locator) {
    const b = await this.box(locator);
    const x = b.x + b.width / 2;
    const y = b.y + b.height / 2;
    await this.call("pointerTo", x, y, null);
    this.clicks.push(this.now());
    await this.call("ripple", x, y);
  }

  /** Glide to the target, ripple, click it for real. */
  async click(locator, { pause = 0.2 } = {}) {
    if (this.filming) await this.press(locator);
    await locator.click();
    if (pause > 0) await this.hold(pause);
  }

  async type(locator, text, { delay = 90 } = {}) {
    if (!this.filming) {
      await locator.fill(text);
      return;
    }
    await this.click(locator, { pause: 0.1 });
    await this.page.keyboard.type(text, { delay });
  }

  // a native <select> popup isn't in the screencast, so set the value under the pointer instead
  async choose(locator, value) {
    if (this.filming) await this.press(locator);
    await locator.selectOption(value);
    await this.hold(0.2);
  }

  /** `input`: the <input type=file> to fill directly if no chooser opens. */
  async pickFile(locator, file, input) {
    const chooser = this.page.waitForEvent("filechooser", { timeout: 5000 }).catch(() => null);
    await this.click(locator, { pause: 0 });
    const fc = await chooser;
    if (fc) await fc.setFiles(file);
    else if (input) await input.setInputFiles(file);
    else throw new Error(`No file chooser opened after clicking ${locator}`);
  }

  /**
   * Wait for a real page state. With `speedUp` (default) the wait plays `factor` (default
   * `fastFactor`) times faster in the video, with a "Sped up" badge once it lasts more than half
   * a second. `target` is a locator (wait until visible) or an async check, polled until it
   * returns true.
   */
  async waitFor(target, { timeout = 180_000, speedUp = true, factor = this.config.fastFactor } = {}) {
    const fast = speedUp && this.filming;
    const segment = { start: Date.now() / 1000, end: null, factor };
    if (fast) this.segments.push(segment);
    let badgeShown = false;
    const badgeTimer = fast
      ? setTimeout(() => {
          badgeShown = true;
          this.call("badge", `Sped up ${factor}×`).catch(() => {});
        }, 500)
      : null;
    try {
      if (typeof target !== "function") {
        await target.waitFor({ state: "visible", timeout });
      } else {
        const deadline = Date.now() + timeout;
        while (!(await target())) {
          if (Date.now() > deadline) throw new Error(`waitFor: still not true after ${timeout / 1000} s`);
          await sleep(100);
        }
      }
    } finally {
      if (badgeTimer) clearTimeout(badgeTimer);
      segment.end = Date.now() / 1000;
      if (badgeShown) await this.call("badge", null).catch(() => {});
    }
  }

  async spotlight(locator, label, { timeout } = {}) {
    const b = await this.box(locator, timeout);
    await this.call("spotlight", b, label ?? null);
  }

  async clearSpotlight() {
    await this.call("clearSpotlight");
  }

  async hidePointer() {
    await this.call("hidePointer");
  }

  /** Full-screen card. `s.card({})` shows only the background (use it in `prepare`). */
  async card(spec) {
    await this.call("hidePointer");
    await this.call("card", spec);
  }

  async closeCard() {
    await this.call("closeCard");
  }

  async list(spec) {
    await this.call("list", spec);
  }

  async closeList() {
    await this.call("closeList");
  }

  async still(name) {
    if (!this.stillsDir) return;
    await sleep(400); // score ring and chart lines animate in
    const file = path.join(this.stillsDir, `${name}.png`);
    await this.page.screenshot({ path: file });
    this.log(`  still ${path.basename(file)}`);
  }
}

/** Wall-clock seconds → output seconds from `realStart`, with sped-up `segments` compressed. */
function mapOutput(t, realStart, segments) {
  let out = t - realStart;
  for (const segment of segments) {
    if (t <= segment.start) continue;
    const end = Math.min(t, segment.end ?? t);
    out -= (end - segment.start) * (1 - 1 / segment.factor);
  }
  return out;
}
