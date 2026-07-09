# For builders

How to run, test, and extend every part of the repository — and how this
book's own images were generated.

## Layout

```
dreamlayer/
├── halo-lua/            device firmware (Lua)
│   ├── main.lua         the ~20 fps tick loop and card queue
│   ├── app/             state machine, IMU gestures
│   ├── ble/             framing, message types, host comm
│   ├── display/         renderer, horizon, materials, palette, animations,
│   │                    typography, particles, parallax, dream renderer, prism
│   └── compat/          the frame adapter (the hardware seam table)
├── host-python/
│   └── src/dreamlayer/
│       ├── orchestrator/  the hub (see the mind chapters)
│       ├── ai_brain/      router, verify, saga; server/ = the Mac Brain
│       ├── hud/           Python mirror renderer, cards, goldens, motion math
│       ├── bridge/        BLE bridge + the Lua raster harness
│       ├── demo/          the emissive overlay / film pipeline
│       ├── plugins/       the plugin API, validation gate, store client,
│       │                  and the first-party plugins
│       ├── reality_compiler/  v2: rehearsal, figments, native timers
│       ├── simulator/     the Python Halo Simulator (the real stack, no glasses)
│       ├── capabilities.py  the 58-seam capability report
│       └── tests/         the whole suite lives here
│   └── packaging/       the macOS .dmg app (py2app, entitlements, launch shim)
├── phone-app/           Expo / React Native (plus the App Store kit: fastlane, i18n)
├── laptop-companion/    the minimal context agent + macOS installer
├── examples/            hello-lens — the ten-minute plugin tutorial, CI-tested
├── registry/            the plugin marketplace catalog (index + packages)
├── registry-api/        the social-layer Cloudflare Worker (api.dreamlayer.app)
├── landing/             the deployed site (dreamlayer.app: home, simulator, store, playground)
├── web/                 the Vite/TS site rebuild + the WebBLE playground
├── docs/                specs; docs/gitbook/ is this book
└── scripts/             demos, exporters, the Halo lab
```

## Running each runtime

```bash
# The Python engine (hub + Brain + HUD mirror); profiles pull optional extras
pip install -e ./host-python                     # core, zero optional deps
pip install -e "./host-python[profile-mac]"      # the full Brain

# The Mac Brain server + control panel
python -m dreamlayer.ai_brain.server --token <token>     # port 7777

# The Halo Simulator — the whole product, no glasses
python -m dreamlayer.simulator                            # cockpit on :8765

# What is switched on, per machine
python -m dreamlayer.capabilities                         # the live report

# The phone app
cd phone-app && npm install && npx expo start             # Expo Go on your phone

# End-to-end walkthrough (install, run, pair): docs/TESTING.md
```

## The test suites

```bash
cd host-python && python -m pytest -q     # 1,803 passing at time of writing
```

- **Python**: unit + live-HTTP server tests (the suite boots the real Brain
  on a loopback port), pairing codec parity, verify parsing, saga, profile
  bridge, and all the orchestrator engines. Requires `pytest`; two dream
  engine tests additionally use `pytest-asyncio`.
- **The Lua raster harness** (`bridge/lua_raster.py`, requires `lupa` +
  Pillow): boots the actual device Lua against a software `frame`, counts
  draw calls and font switches, and asserts the Meridian contracts —
  draw budget (max 420 calls on measured worst frames), palette write budget
  (8/tick), particle pool (24), the strobe guard, reduce-motion stillness
  (settled frames pixel-identical), Solid richness floors (at least 1.25x
  pre-Solid lit pixels), typography metrics (glyph advances within +-2 px of
  the reference face), and Lua-to-Python motion-constant parity.
- **Phone**: `npx tsc --noEmit` (strict TypeScript). No test runner in the
  package today.

## Golden images — every card as a still

```bash
python -m dreamlayer.hud.golden_images --generate --dir out/goldens   # 23 deterministic keys
python - <<'PY'
from dreamlayer.hud.cards import ALL_SAMPLES
from dreamlayer.hud.golden_images import generate_golden
for key in ALL_SAMPLES:                 # all 31 sample cards
    generate_golden(key, "out/goldens")
PY
```

256x256 circular PNGs from the mirror renderer; regression diffing tolerates
8/255 per channel on at most 2 percent of pixels. Device-accurate goldens —
rendered by the *device Lua* through the harness — come from
`python -m dreamlayer.hud.export_cinema_v2_golden` and live under
`assets/cinema_v2/golden/`.

## The demo pipeline — real HUD, compositing-ready

`host-python/src/dreamlayer/demo/` renders storyboards of real cards into
emissive overlays (the waveguide look) over a dark plate. Pure PIL + numpy;
no ffmpeg needed.

```bash
python -m dreamlayer.demo --list                 # storyboards
python -m dreamlayer.demo the_tour out/the_tour  # the 8-card, ~32 s montage
python -m dreamlayer.demo all out/demo           # every storyboard
python -m dreamlayer.demo catalog out/catalog    # every feature clip + master film + catalog.md
```

Each scene directory gets transparent `overlays/`, an EDL `manifest.json`, a
composited `preview.gif`, and a `poster.png`; `catalog` adds the master film
and `catalog.md` — a generated narration script in lockstep with the film's
beat order. `demo/README.md`, `STORYBOARDS.md`, and `AI_VIDEO.md` document
the video workflow (the honesty rule: the HUD is always real; AI may only
draw the world behind it).

## Motion exports

```bash
pip install lupa
python scripts/export_meridian_motion.py    # -> out/meridian_motion/*.gif
```

Steps the device code on a 50 ms clock and writes PNG sequences + GIFs: wake
and aurora, focus physics, the save moment, the loading chase, the promise
shatter, the prism bloom. Sibling exporters: `scripts/run_demo_prism.py`,
`scripts/run_demo_palette_cycle.py`, `scripts/anim_preview.py` (per-card
enter/hold/exit GIFs, pure PIL), `scripts/run_demo_cinema.py` (the 45 s v1
reel).

## The Halo lab and device scripts

`scripts/halo_lab.py` runs scripted scenarios (`scripts/scenarios/*.json`)
through the emulator/raster stack, producing step PNGs, a contact sheet, a
timeline GIF, and a report; `scripts/halo_bridge.py` plays the same scenarios
on a real Halo over BLE; `scripts/upload.py` deploys the Lua. A dozen
`scripts/run_demo_*.py` files exercise individual lenses end to end
(AI brain tiers, the Brain app over HTTP, object lens, provenance,
commitment drift, confluence, REM, Reality Compiler v2, edge cases).

## How this book's assets were made

Everything under `docs/gitbook/assets/` is reproducible from the repo:

| Assets | Command |
|---|---|
| `assets/cards/*.png` (31) | `generate_golden(key, dir)` over `ALL_SAMPLES` |
| `assets/device/*.png` | copied from `assets/cinema_v2/golden/` (device-Lua renders) |
| `assets/motion/*.gif` | `python scripts/export_meridian_motion.py` |
| `assets/demo/catalog/` | `python -m dreamlayer.demo catalog <dir>` (master GIF downscaled for the repo; feature posters and overlays pruned) |
| `assets/panel/*.png` | boot the Brain server, seed folders/people/events, screenshot headlessly (Playwright) |
| `assets/phone/*.png` | `npx expo export --platform web`, serve `dist/` with SPA fallback, screenshot at phone size |

## Extending

- **A new HUD card** is device-Lua-first: a draw function and DRAW entry in
  `renderer.lua`, a constructor in `cards.lua` and `hud/cards.py`, a sample
  in `ALL_SAMPLES`, mirror parity in `hud/renderer.py`, and raster-harness
  tests (budget, richness, reduce-motion) — the O3 conversation cards
  (FactCheck, AnswerAhead, OracleReply, Hark) are the template.
- **A new brain tier or provider** implements the two-method `VisionBrain` /
  `KnowledgeBrain` protocols and registers with the router.
- **A new device** implements the BLE framing and the `frame` adapter
  surface; everything above the seam is unchanged (a Brilliant Frame
  adapter already exists behind the `frame-sdk` capability).
- **A first plugin** takes ten minutes: `examples/hello-lens/` is the
  tested tutorial, and [Open source](open-source.md) covers the DCO,
  policies, and the one command that must stay green.
- **An optional integration** follows the add-alongside convention in
  CONTRIBUTING.md — a sibling adapter file, a try-import, a fallback to the
  built-in, and an entry in the capability catalog.
