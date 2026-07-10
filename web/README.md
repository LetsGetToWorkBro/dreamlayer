# DreamLayer landing page

The marketing site for DreamLayer: a single continuous-scroll story in which the
product's real HUD thinks, remembers, and fact-checks in front of the visitor.

> Also in this directory: **`playground.html`** — the WebBLE dev playground that
> drives the Halo / Frame HUD straight from a browser over Bluetooth. It is
> independent of this Vite site (a single self-contained file). See
> [`PLAYGROUND.md`](./PLAYGROUND.md).

## The hard rule

Every HUD pixel on this page is output of the repo's own renderer
(`dreamlayer.hud.renderer` via the `dreamlayer.demo` tooling). Do not hand-draw,
mock, or approximate HUD elements — for a product whose headline feature is
truth, a faked demo would undercut the whole pitch. The world *behind* the HUD
(the "plates") is the repo's synthetic POV stand-in and may be stylized freely.

## Stack

Vite + vanilla TypeScript, GSAP ScrollTrigger, Lenis. Chosen because the page is
one linear scroll narrative with no client state beyond scroll position — a
framework would add payload and a hydration story for zero benefit. ScrollTrigger
is the battle-tested pin/scrub engine; Lenis (~3 KB) adds the inertial scroll
that makes scrubbed scenes feel filmic. Under `prefers-reduced-motion` neither
is initialized (the motion module is not even downloaded): the page becomes a
calm static document in which every scene shows its hold pose.

Instead of shipping video, the site composites the renderer's transparent
emissive overlays live in the browser with `mix-blend-mode: plus-lighter`
(`screen` fallback) over the plates — the exact additive math the demo tool's
compositor uses — and scrubs each act's `manifest.json` timings against scroll.
Real renderer output, ~1 MB of assets for the whole page, resolution-independent.

## Commands

```bash
npm install
npm run dev        # dev server
npm run build      # typecheck + production build to dist/
npm run preview    # serve the production build

npm run assets     # regenerate all product renders (see below)
npm run shoot      # Playwright screenshots (desktop / mobile / reduced motion)
```

## Asset pipeline

Optimized assets are committed under `public/assets/` so the site builds with
npm alone. To regenerate them from the product renderer (deterministic — fixed
seeds and card content, so a rerun leaves git clean):

```bash
pip install -e "../host-python[dev]"   # Pillow + numpy + lupa, headless
npm run assets                          # = assets:render + assets:build
```

- `scripts/render_scenes.py` renders the demo storyboards (`veritas`,
  `answer_ahead`, `owe_someone`, plus an `juno` scene composed from the same
  real cards), the POV plates at 16:9 and 9:16 (`synth_plate`, one seed per
  section), the curated emissive card stills, and the real device animations
  (`scripts/export_meridian_motion.py`) into `.asset-src/`.
- `scripts/generate-assets.mjs` (sharp) converts everything to WebP/AVIF,
  assembles the animated loops, rewrites the scene manifests to point at the
  optimized files, and fails the run if size budgets are exceeded.

## How an act works

Each pinned act is driven by its scene's `manifest.json` (an EDL from
`host-python/src/dreamlayer/demo/scene.py`): timeline seconds map 1:1 to
manifest seconds, each beat is positioned by its fractional `anchor`/`width`
inside an invisible 9:16 frame centered in the stage (so placement is
viewport-independent), and each beat arrives with the renderer's own ease —
ease-out-cubic fade while settling from 0.94 scale with a slight upward drift.
The site does not invent motion; it replays the product's.

## Conventions

- Design tokens in `src/styles/tokens.css` are derived 1:1 from
  `host-python/src/dreamlayer/hud/themes.py` and the phone app theme. Do not
  invent colors, easings, or durations.
- No emojis anywhere: copy, code, alt text, commit messages.
- Pre-hardware honesty: the only call to action is early access / waitlist.
  By default the CTA is a mailto link; set `VITE_WAITLIST_ENDPOINT` at build
  time to swap in an inline email form (Formspree-style JSON POST).
- All animation is transform/opacity only; never put a CSS `filter` on a
  blended `.beat` (it would isolate it from the blend group).
