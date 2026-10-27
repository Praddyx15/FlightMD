/**
 * Click, transition sweep and music pad, made in code so the video has no third-party audio to
 * license. Deterministic: the same inputs give the same samples on every render.
 */

/** Seeded PRNG (mulberry32), so noise is identical between renders. */
function random(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A soft click, about 60 ms, peak about 0.5. */
export function clickSound(sampleRate) {
  const length = Math.round(0.06 * sampleRate);
  const out = new Float32Array(length);
  const rnd = random(7);
  let low = 0;
  const a = 1 - Math.exp((-2 * Math.PI * 4000) / sampleRate);
  for (let i = 0; i < length; i++) {
    const t = i / sampleRate;
    const tone = (0.6 * Math.sin(2 * Math.PI * 2300 * t) + 0.4 * Math.sin(2 * Math.PI * 1150 * t)) * Math.exp(-t / 0.006);
    low += a * (rnd() * 2 - 1 - low); // soften the noise burst
    const noise = low * Math.exp(-t / 0.0025);
    out[i] = 0.5 * (0.8 * tone + 0.6 * noise);
  }
  return out;
}

/** A gentle air sweep of `seconds`, peak about 0.5, centred in its buffer. */
export function whooshSound(sampleRate, seconds = 0.55) {
  const length = Math.round(seconds * sampleRate);
  const out = new Float32Array(length);
  const rnd = random(11);
  let lp = 0;
  let hp = 0;
  const hpA = 1 - Math.exp((-2 * Math.PI * 180) / sampleRate);
  let peak = 0;
  for (let i = 0; i < length; i++) {
    const p = i / length;
    const cutoff = 350 + 2600 * Math.sin(Math.PI * p) ** 2;
    const a = 1 - Math.exp((-2 * Math.PI * cutoff) / sampleRate);
    lp += a * (rnd() * 2 - 1 - lp);
    hp += hpA * (lp - hp);
    const value = (lp - hp) * Math.sin(Math.PI * p) ** 2;
    out[i] = value;
    peak = Math.max(peak, Math.abs(value));
  }
  if (peak > 0) for (let i = 0; i < length; i++) out[i] *= 0.5 / peak;
  return out;
}

const CHORDS = [
  [45, 52, 59, 60], // A minor (add 9): A2 E3 B3 C4
  [41, 48, 52, 57], // F major 7: F2 C3 E3 A3
  [48, 55, 59, 62], // C major 7 (add 9): C3 G3 B3 D4
  [43, 50, 55, 59], // G major: G2 D3 G3 B3
];

const midiToHz = (note) => 440 * 2 ** ((note - 69) / 12);

/**
 * An ambient pad of `seconds` (stereo Float32Arrays at `sampleRate`), peak 0.5, with a 2 s
 * fade-in and a 3 s fade-out. Chords last `chordSeconds` and overlap by `blendSeconds`; left and
 * right are detuned a little for width.
 */
export function musicBed(seconds, sampleRate = 48000, { chordSeconds = 6.4, blendSeconds = 1.6 } = {}) {
  const length = Math.max(1, Math.round(seconds * sampleRate));
  const left = new Float32Array(length);
  const right = new Float32Array(length);
  const chordCount = Math.ceil(seconds / chordSeconds) + 1;

  for (let k = 0; k < chordCount; k++) {
    const notes = CHORDS[k % CHORDS.length];
    const start = k * chordSeconds - blendSeconds / 2;
    const end = start + chordSeconds + blendSeconds;
    const i0 = Math.max(0, Math.floor(start * sampleRate));
    const i1 = Math.min(length, Math.ceil(end * sampleRate));
    if (i0 >= i1) continue;
    for (const note of notes) {
      const f = midiToHz(note);
      const gain = note < 48 ? 0.15 : 0.11;
      const stepL = (2 * Math.PI * f * (1 - 0.0012)) / sampleRate;
      const stepR = (2 * Math.PI * f * (1 + 0.0012)) / sampleRate;
      let phaseL = (note * 1.37) % (2 * Math.PI);
      let phaseR = (note * 2.11) % (2 * Math.PI);
      phaseL += stepL * i0;
      phaseR += stepR * i0;
      for (let i = i0; i < i1; i++) {
        const t = i / sampleRate;
        // raised-cosine blend in and out of each chord
        const fadeIn = Math.min(1, (t - start) / blendSeconds);
        const fadeOut = Math.min(1, (end - t) / blendSeconds);
        const env = 0.5 - 0.5 * Math.cos(Math.PI * Math.max(0, Math.min(fadeIn, fadeOut)));
        const sL = Math.sin(phaseL);
        const cL = Math.cos(phaseL);
        const sR = Math.sin(phaseR);
        const cR = Math.cos(phaseR);
        // fundamental + soft 2nd and 3rd harmonics (sin 2x = 2 sin cos; sin 3x = 3 sin - 4 sin^3)
        left[i] += gain * env * (sL + 0.28 * 2 * sL * cL + 0.08 * (3 * sL - 4 * sL * sL * sL));
        right[i] += gain * env * (sR + 0.28 * 2 * sR * cR + 0.08 * (3 * sR - 4 * sR * sR * sR));
        phaseL += stepL;
        phaseR += stepR;
      }
    }
  }

  let peak = 0;
  for (let i = 0; i < length; i++) {
    const t = i / sampleRate;
    const breathe = 1 + 0.12 * Math.sin(2 * Math.PI * 0.07 * t);
    const fade = Math.min(1, t / 2, (seconds - t) / 3);
    const g = breathe * Math.max(0, fade);
    left[i] *= g;
    right[i] *= g;
    peak = Math.max(peak, Math.abs(left[i]), Math.abs(right[i]));
  }
  if (peak > 0) {
    const scale = 0.5 / peak;
    for (let i = 0; i < length; i++) {
      left[i] *= scale;
      right[i] *= scale;
    }
  }
  return [left, right];
}
