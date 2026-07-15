# Demo Kit

Reusable tooling for producing DreamLayer marketing/demo media. Everything here
was used to generate the app-demo and lens-demo packs (Discord content kit,
feature walkthroughs, coding montages). Two systems share one folder:

1. **App demos** — screenshot/drive the real UIs (Mac Brain panel, phone app,
   web pages) and frame them in device mockups, with an optional driven cursor
   (move, click ripple, scroll, letter-by-letter typing).
2. **Lens demos** — render real HUD cards through the actual on-device
   renderer, apply the circular glass treatment, and build feature spotlights,
   coding montages, and "lens pops up" payoffs.

**Honesty rule for everything here:** the interface is always the real code —
the real renderer, the real panel HTML, the real landing pages. The only
composited elements are device chrome (window/phone frames), the demo cursor,
and clearly-labeled stubbed data where a live backend can't exist headlessly
(e.g. discovery results in a capture box with no agents running). Hide
environment-only artifacts (offline banners, loading skeletons), never product
UI.

## Prerequisites

- Python venv with `Pillow` + `numpy` (plus the repo's `host-python/src` on
  `sys.path` — the scripts handle that themselves).
- `ffmpeg` for encoding (mp4 + palette GIFs).
- Node + Playwright + a Chromium for the capture scripts. Overridable via env:
  `PLAYWRIGHT_HOME` (playwright module dir) and `CHROME_BIN` (chromium binary).

Scripts exchange data through `/tmp` working dirs (documented per script below);
outputs are frame sequences that ffmpeg encodes.

## System 1 — app demos

| Script | What it does |
|---|---|
| `devices.py` | Shared framing library: `iphone()`, `macwindow()`, `browserwindow()`, drop `shadow()`, branded `scene()` poster background. |
| `shoot_web.js` | Serves `landing/` locally, screenshots Plugin Store / Lens Builder / Playground (dismisses the builder tour, hides env-only banners), cycles the builder preview backgrounds. → `/tmp/web_out` |
| `render_panel_html.py` | Renders the Brain panel (`ai_brain/server/panel.py`) to `/tmp/panel_demo.html` for the capture scripts. |
| `shoot_panel.js` | Panel feature capture, element-cropped (Your-API fold, local/remote warning states). → `/tmp/panel_shots` |
| `shoot_panel2.js` | Driven walkthrough of the Model card: cursor moves/clicks (ripple), scrolls, focuses inputs, types letter-by-letter, opens the provider dropdown, clicks Save (toast). Writes per-frame captions to `caps.json`. → `/tmp/panel_shots2` |
| `shoot_panel3.js` | Whole-app walkthrough: starts on the Home dashboard, clicks Intelligence in the sidebar, opens Your API, auto-scan finds local agents (stubbed discovery), one-tap Connect. → `/tmp/panel_shots3` |
| `build_panel_demo.py` / `2` / `3` | Frame those captures in a Mac window on the branded poster, burn in captions. → frames for ffmpeg |
| `build_apps.py` | Phone + Mac app tours from the gitbook screenshots (`docs/gitbook/assets/{phone,panel}`): framed posters, fanned montages, crossfade tour sequences. → `/tmp/apps_out` |
| `build_demos.py` | Web-page scroll-through demos + builder background-cycle. → `/tmp/demos_out` |
| `build_devkit.py` | Assembles store/builder/dev hero posters from the captures. → `/tmp/devkit_out` |
| `build_reel.py` | Portrait 9:16 "build → prove → ship" reel + Playground hero. → `/tmp/reel_out` |

Typical flow (panel walkthrough):

```bash
python render_panel_html.py                      # -> /tmp/panel_demo.html
node shoot_panel3.js /tmp/panel_shots3           # driven capture + caps.json
python build_panel_demo3.py /tmp/paneldemo3_out  # frame + captions
ffmpeg -framerate 24 -i /tmp/paneldemo3_out/frames/f_%04d.png \
  -vf scale=1000:-2 -c:v libx264 -pix_fmt yuv420p -crf 23 -movflags +faststart demo.mp4
```

## System 2 — lens demos

| Script | What it does |
|---|---|
| `gen.py` | Core glass-lens pipeline: photo plates, emissive HUD overlay (real renderer), dome/glint/disc maps (`docimg/`), animated WebP output. |
| `emberstasis.py` | Custom card faces for Ember (4 spaced-repetition states) + Stasis, registered on the real `CardRenderer`. |
| `newlens.py` | Custom card faces for the Innovation-pass lenses (Candor, Thread, Waypath, Sous, Session…). |
| `feature_batch.py` | Per-feature content kit: black device display + two channel themes (Feature Spotlight / Sim Window), human copy. |
| `feature_kit.py` | Earlier single-feature variant of the same. |
| `reel.py` | Circular-lens HUD reel (signature moments over a dim world, or black device mode). |
| `dev_visuals.py` | Dev/SDK story: CLI terminal transcript, plugin.py + plugin.json code window, `plugins preview` device render. |
| `term_type.py` | Regenerates the terminal frames with true letter-by-letter typing. → `/tmp/dev_out/term` |
| `build_popup.py` | Terminal types the CLI flow, then the rendered lens pops up (scale + glow) as the payoff. |
| `montage_feature.py` | **Generator**: a per-feature coding montage — branch → write code (char-typed, syntax colors) → tests pass → preview → the real lens pops up. Add features by extending its `SPECS` dict. |

Typical flow (feature montage):

```bash
python montage_feature.py veritas /tmp/montage_out
ffmpeg -framerate 30 -i /tmp/montage_out/veritas/f/f_%04d.png \
  -vf scale=1200:-2 -c:v libx264 -pix_fmt yuv420p -crf 23 -movflags +faststart build_veritas.mp4
```

`docimg/` holds the three maps the glass treatment needs (`mask2.png` disc,
`sphere3.png` dome shading, `glint2.png` glass glint).

## Tips

- GIFs: use the two-pass palette (`palettegen`/`paletteuse`) shown above for
  small, clean files; mp4s at CRF 23–25 land in the 200–600 KB range.
- 9:16 verticals: pad any landscape demo with `pad=1080:1920:(ow-iw)/2:(oh-ih)/2`
  plus `drawtext` title/caption (see the session's `vpad` recipe in git history).
- Keep favicon'd captions honest: label anything simulated, and prefer sample
  "Demo Mode" data the apps themselves ship.

## System 3 — voiced videos (ElevenLabs narration)

Proven flow from the 0.1.0 install video. The trick: don't cut the audio to the
video — **re-time the video to the read**.

1. Write the script in blocks whose first words are unique (`vo_blocks.py`'s
   `OPENERS`, or pass your own openers JSON). Generate ONE continuous take in
   ElevenLabs (stability ~0.55, similarity ~0.85, style low).
2. Transcribe with word timestamps (`faster-whisper`, `base.en`, int8 CPU) to
   `/tmp/words_<tag>.json`, then `vo_blocks.py <tag>` → block boundaries.
3. Size each video section to its block (see `yt3.py` — the audio-driven
   variant of `yt2.py`; both use `macui.py` for the desktop chrome and print a
   `sections.json` of section start times).
4. `vo_mix.py <take> <video> <out>` places each block at its section start and
   loudness-normalizes (-16 LUFS).

`vo_head_*.{py,sh}` are the experimental webcam-bubble half (local Wav2Lip:
clone Rudrabha/Wav2Lip, CPU torch venv, weights from the camenduru HF mirror,
face-crop constants measured with the included cascade snippet). It works and
stays fully local, but mouth-region quality at 2026 standards is marginal —
shipped video went voice-only. Kept for reference.

**Privacy rule (enforced by this directory's `.gitignore`): no media is ever
committed here.** Voice takes, reference footage, and finished videos with a
real person's face or voice are deliverables, not repo content.
