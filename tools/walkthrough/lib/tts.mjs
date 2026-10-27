/**
 * Narration with Kokoro (82M-parameter open-weight TTS, Apache-2.0) through kokoro-js, on the
 * CPU, offline after the first model download. Each line is cached by a hash of the model,
 * voice, speed and text, so re-renders only synthesise lines that changed.
 *
 * Draft mode skips the voice and estimates each line's length from its word count.
 */

import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { readWav, trimSilence, writeWav } from "./wav.mjs";

/** Words per second used to estimate line length in draft mode (Kokoro at speed 1 is close). */
const DRAFT_WORDS_PER_SECOND = 2.6;

/** The text Kokoro reads for a scene: `speak` (pronunciation hints) or the caption text. */
export function spokenText(scene) {
  return (scene.speak ?? scene.say).trim();
}

/**
 * Synthesise every scene's line. Returns Map<sceneId, { samples: Float32Array | null,
 * sampleRate, duration }>; `samples` is null in draft mode.
 */
export async function synthesizeAll(scenes, { voice, speed, model, revision, dtype, cacheDir, draft, log }) {
  const result = new Map();
  if (draft) {
    for (const scene of scenes) {
      const words = spokenText(scene).split(/\s+/).filter(Boolean).length;
      result.set(scene.id, { samples: null, sampleRate: 24000, duration: words / DRAFT_WORDS_PER_SECOND + 0.3 });
    }
    return result;
  }

  await mkdir(cacheDir, { recursive: true });
  let tts = null;
  for (const scene of scenes) {
    const text = spokenText(scene);
    const key = createHash("sha256").update(JSON.stringify([model, dtype, voice, speed, text])).digest("hex").slice(0, 20);
    const file = path.join(cacheDir, `${key}.wav`);
    if (existsSync(file)) {
      const { channels, sampleRate } = await readWav(file);
      result.set(scene.id, { samples: channels[0], sampleRate, duration: channels[0].length / sampleRate });
      continue;
    }
    if (!tts) {
      log(`Loading the Kokoro voice model (${model} at ${revision.slice(0, 7)}, ${dtype}); the first run downloads about 90 MB.`);
      const { KokoroTTS } = await import("kokoro-js");
      const { AutoTokenizer, StyleTextToSpeech2Model } = await import("@huggingface/transformers");
      // KokoroTTS.from_pretrained takes no revision, so load its two parts at the pinned one
      const [weights, tokenizer] = await Promise.all([
        StyleTextToSpeech2Model.from_pretrained(model, { dtype, device: "cpu", revision }),
        AutoTokenizer.from_pretrained(model, { revision }),
      ]);
      tts = new KokoroTTS(weights, tokenizer);
      const voices = Object.keys(tts.voices ?? {});
      if (voices.length > 0 && !voices.includes(voice)) {
        throw new Error(`Kokoro has no voice '${voice}'. Available: ${voices.join(", ")}`);
      }
    }
    log(`Voice: ${scene.id}`);
    const audio = await tts.generate(text, { voice, speed });
    const sampleRate = audio.sampling_rate;
    const samples = trimSilence(Float32Array.from(audio.audio), sampleRate);
    await writeWav(file, [samples], sampleRate);
    result.set(scene.id, { samples, sampleRate, duration: samples.length / sampleRate });
  }
  return result;
}
