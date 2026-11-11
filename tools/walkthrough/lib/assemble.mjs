/**
 * Joins the recorded scene clips into the finished video. The picture is cross-faded with
 * `xfade` and encoded once. Voice lines, clicks and the transition sweeps are mixed here in
 * Node into one dialog track, the music is ducked under it w/ `sidechaincompress`, and
 * two-pass `loudnorm` brings it to the target. Also writes the WebVTT captions, a thumbnail
 * and the manifest that verify.mjs reads.
 */

import { copyFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { ffmpeg, measureLoudness, num, vttTime } from "./ffmpeg.mjs";
import { clickSound, musicBed, whooshSound } from "./sound.mjs";
import { mixInto, writeWav } from "./wav.mjs";

/** Start time of every scene in the finished video, given clip durations and the cross-fade. */
export function timeline(durations, crossfade) {
  const fade = durations.length > 1 ? crossfade : 0;
  const starts = [];
  let t = 0;
  for (let i = 0; i < durations.length; i++) {
    starts.push(i === 0 ? 0 : t - fade);
    t = starts[i] + durations[i];
  }
  return { starts, fade, total: t };
}

async function joinPicture({ clips, starts, fade, total, config, file }) {
  const fps = config.output.fps;
  const args = [];
  for (const clip of clips) args.push("-i", clip);
  const parts = clips.map((_, i) => `[${i}:v]fps=${fps},settb=AVTB,format=yuv420p,setsar=1[v${i}]`);
  let last = "v0";
  for (let i = 1; i < clips.length; i++) {
    const out = `x${i}`;
    parts.push(`[${last}][v${i}]xfade=transition=${config.transition}:duration=${num(fade)}:offset=${num(starts[i])}[${out}]`);
    last = out;
  }
  args.push(
    "-filter_complex", parts.join(";"),
    "-map", `[${last}]`,
    "-t", num(total),
    "-c:v", "libx264",
    "-preset", "slow",
    "-crf", "18",
    "-profile:v", "high",
    "-pix_fmt", "yuv420p",
    "-color_range", "tv",
    "-colorspace", "bt709",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
    "-r", String(fps),
    "-g", String(fps * 2),
    "-movflags", "+faststart",
    "-an",
    file,
  );
  await ffmpeg(args);
}

/**
 * @param {object} p
 * @param {Array<{id: string, clip: string, duration: number, voice: {samples: Float32Array|null, sampleRate: number, duration: number}, clicks: number[], cues: {text: string, start: number, end: number}[], thumbnail?: boolean}>} p.scenes
 */
export async function assemble({ scenes, config, outDir, workDir, draft, music, name, log }) {
  const { starts, fade, total } = timeline(
    scenes.map((s) => s.duration),
    config.crossfadeSeconds,
  );
  for (const scene of scenes) {
    if (scenes.length > 1 && scene.duration <= 2 * fade) throw new Error(`Scene "${scene.id}" is too short for the cross-fade.`);
  }

  log("Joining the scenes");
  const picture = path.join(workDir, "picture.mp4");
  await joinPicture({ clips: scenes.map((s) => s.clip), starts, fade, total, config, file: picture });

  const file = path.join(outDir, `${name}.mp4`);
  let loudness = null;
  let musicSource = null;
  if (draft) {
    await copyFile(picture, file);
  } else {
    log("Mixing voice, clicks and music");
    const sampleRate = scenes.find((s) => s.voice.samples)?.voice.sampleRate ?? 24000;
    const length = Math.ceil(total * sampleRate);
    const voiceOnly = new Float32Array(length);
    const dialog = new Float32Array(length);
    const click = clickSound(sampleRate);
    const whoosh = whooshSound(sampleRate);
    scenes.forEach((scene, i) => {
      if (scene.voice.samples) {
        mixInto(voiceOnly, scene.voice.samples, starts[i] + config.leadSeconds, sampleRate);
        mixInto(dialog, scene.voice.samples, starts[i] + config.leadSeconds, sampleRate);
      }
      for (const t of scene.clicks) mixInto(dialog, click, starts[i] + t, sampleRate, config.clickGain);
      if (i > 0) {
        const middle = starts[i] + fade / 2;
        mixInto(dialog, whoosh, middle - whoosh.length / sampleRate / 2, sampleRate, config.whooshGain);
      }
    });
    const voiceFile = path.join(workDir, `${name}-voice.wav`); // read by verify.mjs
    const dialogFile = path.join(workDir, "dialog.wav");
    await writeWav(voiceFile, [voiceOnly], sampleRate);
    await writeWav(dialogFile, [dialog], sampleRate);

    const premix = path.join(workDir, "premix.wav");
    const stereo = "aformat=sample_fmts=fltp:channel_layouts=stereo";
    if (music === false) {
      musicSource = "none";
      await ffmpeg(["-i", dialogFile, "-filter_complex", `[0:a]aresample=48000,${stereo},atrim=0:${num(total)}[out]`, "-map", "[out]", "-c:a", "pcm_f32le", premix]);
    } else {
      const musicArgs = [];
      let shaping = "";
      if (typeof music === "string") {
        musicSource = music;
        musicArgs.push("-stream_loop", "-1", "-i", music);
        shaping = `,afade=t=in:st=0:d=2,afade=t=out:st=${num(Math.max(0, total - 3))}:d=3`;
      } else {
        musicSource = "generated pad (lib/sound.mjs)";
        const bed = path.join(workDir, "music.wav");
        await writeWav(bed, musicBed(total, 48000), 48000);
        musicArgs.push("-i", bed);
      }
      const graph = [
        `[0:a]aresample=48000,${stereo},asplit=2[dlg][key]`,
        `[1:a]aresample=48000,${stereo},volume=${num(config.musicGainDb, 1)}dB${shaping}[bed]`,
        `[bed][key]sidechaincompress=threshold=${config.duck.threshold}:ratio=${config.duck.ratio}:attack=${config.duck.attackMs}:release=${config.duck.releaseMs}[ducked]`,
        `[dlg][ducked]amix=inputs=2:normalize=0:duration=first,atrim=0:${num(total)}[out]`,
      ].join(";");
      await ffmpeg(["-i", dialogFile, ...musicArgs, "-filter_complex", graph, "-map", "[out]", "-t", num(total), "-c:a", "pcm_f32le", premix]);
    }

    log("Levelling loudness (two passes)");
    const target = config.loudness;
    const measured = await measureLoudness(premix, target);
    const loudnorm =
      `loudnorm=I=${target.I}:TP=${target.TP}:LRA=${target.LRA}` +
      `:measured_I=${measured.input_i}:measured_TP=${measured.input_tp}:measured_LRA=${measured.input_lra}` +
      `:measured_thresh=${measured.input_thresh}:offset=${measured.target_offset}:linear=true`;
    await ffmpeg([
      "-i", picture,
      "-i", premix,
      "-filter_complex", `[1:a]${loudnorm},aresample=48000[a]`,
      "-map", "0:v:0",
      "-map", "[a]",
      "-c:v", "copy",
      "-c:a", "aac",
      "-b:a", "192k",
      // noise substitution put a +0.3 dBTP spike into a limited -1.5 dBTP mix
      "-aac_pns", "0",
      "-ar", "48000",
      "-ac", "2",
      "-movflags", "+faststart",
      "-shortest",
      file,
    ]);
    loudness = { before: measured.input_i, target: target.I };
  }

  const cues = [];
  scenes.forEach((scene, i) => {
    const sceneEnd = i + 1 < scenes.length ? starts[i + 1] : total;
    for (const cue of scene.cues) {
      const start = starts[i] + cue.start;
      const end = Math.min(starts[i] + cue.end, sceneEnd);
      if (end - start > 0.2) cues.push({ start, end, text: cue.text, scene: scene.id });
    }
  });
  const vttFile = path.join(outDir, `${name}.vtt`);
  const vtt = ["WEBVTT", ""];
  cues.forEach((cue, i) => vtt.push(String(i + 1), `${vttTime(cue.start)} --> ${vttTime(cue.end)}`, cue.text, ""));
  await writeFile(vttFile, vtt.join("\n"));

  const thumbIndex = Math.max(0, scenes.findIndex((s) => s.thumbnail));
  const thumbAt = starts[thumbIndex] + Math.min(scenes[thumbIndex].duration - 0.5, Math.max(2.5, scenes[thumbIndex].duration * 0.6));
  const thumbnail = path.join(outDir, `${name}-thumbnail.jpg`);
  await ffmpeg(["-ss", num(thumbAt), "-i", picture, "-frames:v", "1", "-q:v", "2", thumbnail]);

  const manifest = {
    file: path.basename(file),
    captions: path.basename(vttFile),
    thumbnail: path.basename(thumbnail),
    created: new Date().toISOString(),
    draft,
    total,
    crossfade: fade,
    leadSeconds: config.leadSeconds,
    music: musicSource,
    loudness,
    scenes: scenes.map((scene, i) => ({
      id: scene.id,
      start: starts[i],
      duration: scene.duration,
      voiceSeconds: scene.voice.duration,
      clicks: scene.clicks.map((t) => starts[i] + t),
      say: scene.say,
    })),
    cues,
  };
  const manifestFile = path.join(outDir, `${name}.manifest.json`);
  await writeFile(manifestFile, JSON.stringify(manifest, null, 2));
  return { file, vttFile, thumbnail, manifestFile, total };
}
