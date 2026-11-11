/**
 * Minimal WAV reading and writing (16-bit PCM) and sample mixing for the voice and effects
 * tracks. Only the files this pipeline writes are read back, so only PCM 16-bit is supported.
 */

import { readFile, writeFile } from "node:fs/promises";

/**
 * Write channels (Float32Array each, same length, nominal range -1..1) as 16-bit PCM WAV.
 * Values beyond ±1 are soft-limited rather than wrapped.
 */
export async function writeWav(file, channels, sampleRate) {
  const count = channels.length;
  const frames = channels[0]?.length ?? 0;
  const dataBytes = frames * count * 2;
  const buffer = Buffer.alloc(44 + dataBytes);
  buffer.write("RIFF", 0, "ascii");
  buffer.writeUInt32LE(36 + dataBytes, 4);
  buffer.write("WAVE", 8, "ascii");
  buffer.write("fmt ", 12, "ascii");
  buffer.writeUInt32LE(16, 16); // fmt chunk size
  buffer.writeUInt16LE(1, 20); // PCM
  buffer.writeUInt16LE(count, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * count * 2, 28);
  buffer.writeUInt16LE(count * 2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36, "ascii");
  buffer.writeUInt32LE(dataBytes, 40);
  let offset = 44;
  for (let i = 0; i < frames; i++) {
    for (let c = 0; c < count; c++) {
      buffer.writeInt16LE(Math.round(softLimit(channels[c][i]) * 32767), offset);
      offset += 2;
    }
  }
  await writeFile(file, buffer);
}

/** Read a 16-bit PCM WAV written by `writeWav`. Returns { channels, sampleRate }. */
export async function readWav(file) {
  const buffer = await readFile(file);
  if (buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error(`${file} is not a WAV file`);
  }
  let offset = 12;
  let format = null;
  while (offset + 8 <= buffer.length) {
    const id = buffer.toString("ascii", offset, offset + 4);
    const size = buffer.readUInt32LE(offset + 4);
    const body = offset + 8;
    if (id === "fmt ") {
      format = {
        audioFormat: buffer.readUInt16LE(body),
        channels: buffer.readUInt16LE(body + 2),
        sampleRate: buffer.readUInt32LE(body + 4),
        bits: buffer.readUInt16LE(body + 14),
      };
    } else if (id === "data") {
      if (!format || format.audioFormat !== 1 || format.bits !== 16) {
        throw new Error(`${file}: only 16-bit PCM WAV is supported`);
      }
      const frames = Math.floor(size / (2 * format.channels));
      const channels = Array.from({ length: format.channels }, () => new Float32Array(frames));
      let p = body;
      for (let i = 0; i < frames; i++) {
        for (let c = 0; c < format.channels; c++) {
          channels[c][i] = buffer.readInt16LE(p) / 32768;
          p += 2;
        }
      }
      return { channels, sampleRate: format.sampleRate };
    }
    offset = body + size + (size % 2);
  }
  throw new Error(`${file} has no audio data`);
}

/** Add `source` into `target` starting at `atSeconds`, scaled by `gain`. Out-of-range parts are dropped. */
export function mixInto(target, source, atSeconds, sampleRate, gain = 1) {
  const start = Math.round(atSeconds * sampleRate);
  for (let i = 0; i < source.length; i++) {
    const j = start + i;
    if (j < 0) continue;
    if (j >= target.length) break;
    target[j] += source[i] * gain;
  }
}

/**
 * Remove leading and trailing near-silence, keeping `padSeconds` on each side, so a voice
 * line starts exactly where it is placed.
 */
export function trimSilence(samples, sampleRate, { threshold = 0.004, padSeconds = 0.03 } = {}) {
  let first = 0;
  while (first < samples.length && Math.abs(samples[first]) < threshold) first++;
  let last = samples.length - 1;
  while (last > first && Math.abs(samples[last]) < threshold) last--;
  if (first >= samples.length) return samples;
  const pad = Math.round(padSeconds * sampleRate);
  return samples.slice(Math.max(0, first - pad), Math.min(samples.length, last + 1 + pad));
}

/** Linear resampling (used only for short effects, never for the voice). */
export function resampleLinear(samples, fromRate, toRate) {
  if (fromRate === toRate) return samples;
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const x = i * ratio;
    const i0 = Math.floor(x);
    const i1 = Math.min(samples.length - 1, i0 + 1);
    const t = x - i0;
    out[i] = samples[i0] * (1 - t) + samples[i1] * t;
  }
  return out;
}

function softLimit(x) {
  if (x > 0.95) return 0.95 + 0.05 * Math.tanh((x - 0.95) / 0.05);
  if (x < -0.95) return -0.95 + 0.05 * Math.tanh((x + 0.95) / 0.05);
  return x;
}
