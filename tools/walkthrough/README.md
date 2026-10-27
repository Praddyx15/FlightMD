# FlightMD walkthrough video

The walkthrough video, the LinkedIn teaser and the screenshots in
[`docs/WALKTHROUGH.md`](../../docs/WALKTHROUGH.md) are rendered by code from the running app,
never recorded or edited by hand:

- **Playwright** drives the real app in Chromium and captures frames (DevTools screencast).
- **Kokoro** reads the narration: a free 82M-parameter voice model running locally on the CPU (via kokoro-js).
- **FFmpeg** joins the scenes with cross-fades, mixes the voice, click sounds and a generated music bed, and levels the loudness.

One command renders a whole video. The story lives in [`scenes.mjs`](scenes.mjs) (the
walkthrough) and [`teaser.mjs`](teaser.mjs): one spoken line per scene, plus the steps that show
it. Change a line or a step, render again, and everything else (timing, captions, sound) follows.

The pipeline is adapted from the AeroAtlas demo video (same author, MIT). Nothing here costs money
or needs an account:

| Tool | Licence |
|---|---|
| Playwright | Apache-2.0 |
| kokoro-js | Apache-2.0 |
| Kokoro-82M voice weights | Apache-2.0 |
| FFmpeg | LGPL/GPL; used as a separate tool, not bundled |

The music bed and the sound effects are synthesised in [`lib/sound.mjs`](lib/sound.mjs), so there
are no third-party audio files to license.

## What the walkthrough shows

About two and a half minutes (the length follows the voice):

1. **Hook:** "Your drone flew badly. The log knows why." and the four questions after a bad flight.
2. **Title card.**
3. **Upload:** the drop zone and its formats, an airframe label, `sample_flawed.ulg` picked through the file chooser, then the progress screen with the time left.
4. **Verdict:** the health score and how many checks were assessed.
5. **Findings:** the flight timeline and the first finding with its time window and confidence.
6. **Show on chart:** the jump to the chart with the finding's window shaded.
7. **Parameter sheet:** the table, Mission Planner and QGroundControl formats, Copy all.
8. **Mark applied:** one change ticked and recorded on the airframe.
9. **Verify:** `sample_clean.ulg` uploaded with the same label (off camera), then the airframe page's verify status.
10. **Trends:** score history, the saved access token, module trends.
11. **Compare:** the two flights side by side.
12. **Export and print:** the export buttons, then the page in print layout.
13. **Units and theme:** imperial units and the light theme.
14. **End card:** the repository link, MIT, the UAV suite, and a note that the logs are synthetic.

Every log is uploaded through the page, the way a user would. `sample_flawed.ulg` and
`sample_clean.ulg` are synthetic flights from `tests/sample_logs/`, and the end card says so.

The teaser (`--story teaser`, 30–40 s) is the hook, one upload, the score with the worst finding,
the parameter change copied, and the end card.

## One-time setup

You need:

- **Node 20 or newer**
- **FFmpeg 5 or newer** on `PATH`, a full build (with libx264). Install it with one of:
  - Windows: `winget install Gyan.FFmpeg`
  - macOS: `brew install ffmpeg`
  - Debian/Ubuntu: `sudo apt install ffmpeg`

Open a new terminal afterwards and check with `ffmpeg -version`. winget, Homebrew and apt check what they download themselves.

A portable copy works too: unzip a build (for example gyan.dev's "essentials") into `tools/walkthrough/.bin/` (git-ignored) and put its `bin` folder first on `PATH` for the session. Check the archive before you unzip it: gyan.dev publishes a `.sha256` file next to every build on https://www.gyan.dev/ffmpeg/builds/ (for `ffmpeg-release-essentials.zip`, download `ffmpeg-release-essentials.zip.sha256` too). The two values must match:

```powershell
(Get-FileHash .\ffmpeg-release-essentials.zip -Algorithm SHA256).Hash   # Windows PowerShell
Get-Content .\ffmpeg-release-essentials.zip.sha256
```

```bash
sha256sum ffmpeg-release-essentials.zip          # Git Bash, Linux; on macOS: shasum -a 256
cat ffmpeg-release-essentials.zip.sha256
```

Other builds work the same way (BtbN's GitHub builds list theirs in `checksums.sha256`). If the values differ, delete the download and fetch it again.

Then, in this folder:

```bash
cd tools/walkthrough
npm install          # playwright + kokoro-js (+ transformers.js, which loads the model)
npm run setup        # downloads Chromium for Playwright (once)
```

Commit the `package-lock.json` that `npm install` writes; the versions in `package.json` are pinned.

The first full render downloads the Kokoro model from Hugging Face (about 90 MB, cached in `node_modules/@huggingface/transformers/.cache/`). Later renders work offline, apart from the map tiles on the report page.

**Model revision.** `config.mjs` pins the model to one Hugging Face commit (`voiceRevision`), so the weights cannot change between renders even if the model repository does. To move to a newer one, look up its `sha` at https://huggingface.co/api/models/onnx-community/Kokoro-82M-v1.0-ONNX, put it in `voiceRevision`, and delete `out/cache/voice/` so every line is spoken again with the new weights (the line cache is keyed by model name, voice, speed and text, not the revision).

## Start FlightMD

Run the API against a scratch data directory, offline, with a rate limit high enough for a few
renders (each walkthrough uploads two logs, the teaser one, `--stills` two). Use a production
build of the web app: it records more smoothly than `npm run dev`.

Terminal 1, repo root, with the API's requirements installed (see the main README):

```bash
export FLIGHTMD_DATA_DIR="$(mktemp -d)" FLIGHTMD_OFFLINE=1 RATE_LIMIT_PER_HOUR=1000
python -m uvicorn api.main:app --port 8000
```

```powershell
$env:FLIGHTMD_DATA_DIR = "$env:TEMP\flightmd-walkthrough"; $env:FLIGHTMD_OFFLINE = "1"; $env:RATE_LIMIT_PER_HOUR = "1000"
python -m uvicorn api.main:app --port 8000
```

Don't set `RATE_LIMIT_PER_HOUR=0`: that is a limit of zero uploads, and every upload gets 429.

Terminal 2:

```bash
cd frontend
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run build    # PowerShell: $env:NEXT_PUBLIC_API_URL="http://localhost:8000"; npm run build
npm start -- -H 127.0.0.1
```

`NEXT_PUBLIC_API_URL` is read at build time, so build again if the API moves.

Each render tags its flights with the first free label among `Quad-1` … `Quad-20`, so renders
don't collide on one API. Once all twenty are taken, stop the API, delete the scratch directory
and start it again.

## Render

Terminal 3, in `tools/walkthrough`:

```bash
npm run draft                     # fast pass: no voice, line lengths estimated → out/walkthrough-draft.mp4
OFFSCREEN=1 npm run walkthrough   # the real thing → out/walkthrough.mp4 (window kept off screen)
npm run verify                    # numbers + review frames for out/walkthrough.mp4

OFFSCREEN=1 npm run teaser        # → out/teaser.mp4
npm run verify -- teaser

npm run stills                    # screenshots → docs/walkthrough/*.png (headless, no video)
```

`npm run stills` is the same as `npm run walkthrough -- --stills`. On Windows PowerShell, set
variables first: `$env:OFFSCREEN="1"; npm run walkthrough`.

A Chromium window opens and plays through the scenes. Don't touch it while it records, and don't minimise it.
- `OFFSCREEN=1` places that window off the visible screen, so you can keep working. This is the recommended mode.
- `HEADLESS=1` runs without any window. FlightMD's charts are SVG, so it usually keeps up; check the review frames afterwards.

**One scene:** `npm run scene -- params` (or `-- verdict,params`) → `out/scene-params.mp4`. The
scenes before it still run, unfilmed, because each one builds on the last (the report from the
upload scene, the label from the mark-applied scene).

### Outputs (in `out/`, git-ignored)

| File | What |
|---|---|
| `walkthrough.mp4`, `teaser.mp4` | 1920×1080, 30 fps, H.264 + AAC 48 kHz stereo, loudness levelled to −16 LUFS |
| `<name>.vtt` | Captions, the same text as the burned-in ones |
| `<name>-thumbnail.jpg` | A frame from the title card |
| `<name>.manifest.json` | Where every scene, caption and click is in the timeline |
| `<name>.seen.json` | The page text of every scene (scanned for error messages by `verify`) |
| `<name>.verify.json`, `review/<name>/` | The verify report and frames from every scene |
| `failed.png` | The page at the moment a step failed, if one did |
| `cache/voice/` | Synthesised voice lines; only changed lines are re-synthesised |

`--stills` writes `docs/walkthrough/01-upload.png` … `14-units-theme.png` (1536×864), the names
`docs/WALKTHROUGH.md` uses. `02-processing.png` is only written when the progress screen was
still up when the report page loaded; the log says so when it wasn't.

### Options

| Option | Effect |
|---|---|
| `--story teaser` | The teaser instead of the walkthrough |
| `--stills` | Screenshots for the written walkthrough instead of a video |
| `--no-music` | Voice and clicks only |
| `--music path/to/track.mp3` | Use your own track instead of the generated pad: looped, faded and lowered under the voice. Use only music you may publish (royalty-free or your own) |
| `VOICE=bm_george` | Another Kokoro voice (for example `af_bella`, `am_michael`, `bf_emma`) |
| `VOICE_SPEED=1.05` | Faster or slower narration (also the quickest fix for a teaser a second too long) |
| `MUSIC_DB=-24` | Music quieter (more negative) or louder |
| `REPO_URL=https://github.com/<you>/FlightMD` | Shown on the end card as the next step |
| `OFFSCREEN=1` | Record in a real browser window placed off the screen (recommended) |
| `HEADLESS=1` | No window at all |
| `FMD_DEBUG_TIMING=1` | Print each step's time and the frame timing per scene (for diagnosing a scene that looks out of step) |
| `APP_URL`, `API_URL` | Where the app runs (defaults `http://localhost:3000`, `http://localhost:8000`) |

## How it works

```
scenes.mjs / teaser.mjs ──► lib/tts.mjs (Kokoro, cached) ──► line lengths
     │
     ▼
record.mjs ── for each scene: prepare (not filmed) → record steps → hold until voice + tail
     │          lib/stage.mjs    clock, captions, pointer, spotlight, sped-up waits, stills
     │          lib/overlay.mjs  in-page captions, callouts, pointer, cards (shadow DOM)
     │          lib/capture.mjs  DevTools screencast → constant-frame-rate clip (after recording)
     ▼
lib/assemble.mjs ── xfade join → voice + clicks + whooshes (Node mix) → ducked music
                    → two-pass loudnorm → <name>.mp4 + .vtt + thumbnail + manifest
```

- **Timing follows the voice.** Each scene lasts as long as its steps or its line (plus a short tail), whichever is longer, and holds at least 1.6 s after its last spotlight or click so the result can be read. The voice starts 0.35 s after the picture. Captions split the line by sentence and are timed by character count.
- **One browser, one story.** The scenes share a page and build on each other, so clips are encoded after the last scene: the app never waits on FFmpeg between two scenes.
- **No loading states on screen.** Page loads and the second upload happen in `prepare`, before recording starts. Waits for an analysis play 4× faster, with a "Sped up" badge once they last more than half a second.
- **Frames are placed by when they were painted**, not when they arrived. Chrome can send them late, so each scene keeps recording until a frame painted after its end has arrived.
- **Real states, not sleeps.** Steps wait for real elements: the report heading, the "Copied" button, the applied-changes confirmation. When the app shows an error instead, the render stops with the app's own message. Holds are only for pacing.
- **Print** is shown by emulating print media: `window.print` is stubbed in the browser so the native dialog never blocks the page.
- **Sound:** the voice leads. The music sits about 21 dB lower and ducks further while the voice speaks. A soft click plays on every click and a gentle sweep on every cut.

## Changing the video

- **Words:** edit `say` in `scenes.mjs` or `teaser.mjs`. Use `speak` when the voice needs a different spelling (for example "Flight M D", "Q Ground Control").
- **Steps:** `s.click`, `s.type`, `s.choose`, `s.pickFile`, `s.waitFor`, `s.spotlight(locator, "why it matters")`, `s.hold`, `s.card`, `s.list`, `s.still` (see the top of `lib/stage.mjs`). Use Playwright locators by role and accessible name, with the text from `frontend/messages/en.json`, as `frontend/e2e/smoke.spec.ts` does. When a UI text changes there, change the locator here.
- **A screenshot for the written walkthrough:** `await s.still("NN-name")` at the point in a scene, and an image link with the same name in `docs/WALKTHROUGH.md`.

## Before sharing

Run through this once:

- [ ] `npm run verify` (and `npm run verify -- teaser`) passes.
- [ ] Look through `out/review/<name>/`: no error states, no half-loaded charts, the progress screen in the upload scene (if it wasn't caught, the voice talks over the report there).
- [ ] Watch once with the sound off: the captions alone tell the story.
- [ ] Listen once with your eyes closed: the voice is clear and the music never competes with it.
- [ ] The end card shows the repository link (`REPO_URL`) and says the logs are synthetic.
- [ ] Upload the `.vtt` with the video.
