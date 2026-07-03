# Meridian Lumen — material physics and living light

## The claim

Meridian won the ontology argument: the display is a place, not a stage.
Lumen wins the *light* argument. Before this pass every surviving motion
was geometric — arcs redrawn per tick, sine breathing, linear luma ramps
— while the hardware's one superpower, a runtime-writable 16-slot
palette over already-lit pixels (1024 luma tiers per slot via
`frame.display.assign_color_ycbcr`), was used in exactly two places.
Lumen makes light itself the animation medium and gives every remaining
motion real material physics. Nothing added carries zero bits: spectacle
comes from *how* information moves and glows, never from new theater —
that is how this pass stays on the right side of the Meridian kill-list.

## The engines (Phase 1)

| Engine | File | What it is |
|---|---|---|
| Springs | `halo-lua/lib/easing.lua` `spring/anticipate` | Closed-form damped spring (pure function of t — deterministic, golden-safe). Presets in `animations.lua`: soft ζ=0.85 (text-adjacent, no visible overshoot), snappy ζ=0.63 (rings/dots, ≤8% rebound — `SPRING_OVERSHOOT_MAX` is asserted in tests). Python twin: `hud/motion_math.py`. |
| Palette animator | `display/palette_animator.lua` | Budgeted luma *programs* (wave / shimmer / flash / sweep / fade) over leased slots. ≤ `PAL_WRITES_MAX = 8` assigns per tick; reduce_motion holds each program's still pose; one-shots auto-stop and restore. |
| Slot leases | `display/palette.lua` `lease/release/owner` | One live writer per slot, structurally. Releasing restores base — a lapsed program can never strand a slot off-base. Extends Meridian's slot-*ownership* fix to slot *animation*. |
| Particles | `display/particles.lua` | One pooled budget (`PARTICLE_BUDGET = 24`, oldest-first eviction). Closed-form physics seeded by `perlin1d` — same seed, same pixels, so hero moments are goldenable. Honest 4bpp fade: dots shrink, streaks shorten, no alpha. reduce_motion spawns nothing. |
| Parallax | `display/parallax.lua` | On-device `frame.imu_data()` at 20fps (no BLE round-trip). Layers shift *against* head rate with depth classes — LOCK 0px (all text, verdicts, privacy), RIM ±1px (day ring), RING ±2px (focus rings), AIR ±3px (particles, prism) — and spring home with a small inertial overshoot when the head stops. Absent sensor / reduce_motion / privacy veil ⇒ hard zero. Worst case rim tip 110+1 < SAFE_RADIUS 112. |

## Where the light lives (Phases 2–3)

- **Horizon aurora** — the 72-segment rim track bands across three
  leased slots; a 12s luma wave makes light flow along the day. Zero new
  geometry; pure idle only; focused/dim/reduce frames keep the static
  ghost track pixel-for-pixel.
- **Notch heartbeat** — fast spring rise, long soft decay. Alive, not
  metronomic. Same cycle, same length range.
- **Premonition shimmer** — the v1 70%-duty visibility blink (the
  codebase's one true temporal dither) is dead. Dots always draw, in the
  `premo` slot whose luma breathes *down* from the ghost base — never
  brighter than before, nothing flickers.
- **Focus physics** — anticipation pull-back past the rim, squash-stretch
  on the flight head (never text), 5-sample phosphor tail cooling through
  the ghost slot, spring "click" on the landing ring, one glint along the
  hold ring's confidence arc as it settles (the ring's color IS the
  confidence — the glint is an overdraw, the settled frame is exactly the
  pre-Lumen static gauge), soft-spring recession that *files* the content
  (SIG_RECEDE_MS 160→200; risk doc pre-cleared 240).
- **Cards** — SavedMemory: spring check + 12-particle burst + chime at
  HOLD. ObjectRecall: rail + trace banded so a conduct wave flows light
  place→object. Listening: `{t="amp"}` (~15 B, capture-time only) makes
  the bars track the wearer's real voice and warm through the voice slot;
  without amp data the v1 look is untouched. Loading: the rotating arc is
  dead — 12 static segments + palette chase at the old RPM (fewer draw
  calls; reduce_motion gets a static ring, strictly better than a frozen
  spinner). TruthLens: three deterministic shards spit as each torn stage
  reveals; one glint runs the settled thread.
- **Hero moments** — promise shatter (state-5 *transition* only: shards
  fall inward + 150ms impact ring; replays never re-break), the wake ring
  (the day assembles radially from the notch over 600ms — draw-order
  gating, no new geometry), the dream door (starfield streaks outward
  into the dream, inward on the way home — answers DELTAS §8's "the dream
  lost its door"), and the privacy grip (parallax freezes to zero the
  frame the veil lands — nothing about the veil may feel ambient).
- **Prism Lens** — rebuilt, and *fixed*: v1 passed raw slot indices as
  draw colors, so the kaleidoscope rendered near-black. Now: spring
  bloom-in, breathing rotation, two counter-rotating halo rings, Perlin
  tip shimmer, AIR-depth float. Rates keep v1's photosensitivity caps.

## SIGNATURES: the `flair` field

`renderer.lua` SIGNATURES gains one optional field, consumed at the
enter→hold transition — not a new code path. `burst` (SavedMemory),
`chase` (Loading), `conduct` (ObjectRecall). Card light programs share
the id `card_light`; `show_card`/`dismiss` stop it, so a crossfade can
never leave two programs fighting over the card slots.

## Rejected, with reasons

- **Temporal luma dithering** — 20fps ⇒ 10Hz square wave: strobe, not
  blend. The dynamic bank already has 1024 honest luma tiers. The strobe
  guard test (no slot luma reverses direction >4×/s) mechanizes this.
- **Sprite hero sequences** — 4KB ≈ 32 BLE chunks starves the palette
  tick and horizon cadence (CINEMA_V2_RISKS §2); deferred until the BLE
  priority queue exists. Everything above is primitives + palette at
  zero new BLE cost (`amp` is ~15 B, capture-time only).
- **Orbital/curved text** — text never moves or distorts. Standing rule.
- **Idle constellations / Lissajous ornaments** — zero-bit decoration;
  exactly what Meridian killed (DELTAS §6).
- **set_pixel scanlines / moiré** — call-budget prohibitive / reads as
  artifact.
- **Radial content stagger** (plan item) — deliberately dropped: at a
  180ms enter over three text rows the geometry-ordered reveal is
  indistinguishable from the time stagger; complexity without a visible
  return.

## Budgets (asserted, not aspirational)

`test_draw_budget.py`: worst composited frame ≤ `DRAW_CALLS_MAX = 420`
primitives (idle aurora, ObjectRecall composite, testimony with spits,
prism at max intensity/symmetry); palette writes ≤ 8/tick; particle pool
≤ 24 global. Zero new ambient BLE streams.

## reduce_motion contract

Unchanged and total: every program holds its still pose, every particle
spawn is a no-op, parallax is zero, the wake reveal shows the whole day
at once, and every reduce path is the pre-Lumen static state (the aurora
band hexes differ from `border_subtle` by one invisible LSB; the banded
track only moves when the animator runs).

## Verification

- Goldens render through the integrated device Lua
  (`export_cinema_v2_golden.py`); regenerated where the scene
  deliberately changed. `sync_dynamic_slots` now syncs *both* palette
  module instances (dot and slash require-strings) — dream/prism cycled
  color never showed in the raster before.
- `scripts/export_meridian_motion.py` — steps the device code on a 50ms
  clock and writes PNG sequences + GIFs (wake+aurora, focus physics,
  save moment, loading chase, promise shatter, prism bloom) to
  `out/meridian_motion/`.
- New suites: `test_motion_math.py` (spring shape, overshoot cap,
  Lua↔Python parity over the whole Lumen constant bank),
  `test_palette_animator.py` (leases, programs, budget, strobe guard),
  `test_particles.py`, `test_parallax.py`, `test_focus_lumen.py`,
  `test_hero_moments.py`, `test_draw_budget.py`, prism color-regression.

## Device-day risks (adds to CINEMA_V2_RISKS.md)

1. **Aurora amplitude on the real panel** — `AURORA_Y_AMP` is one
   constant; the daylight-legibility risk (#1) applies doubly to dim
   luma waves. Tune on glass.
2. **Draw-color→slot resolution on real firmware** — the codebase's
   convention (drawing a dynamic slot's base hex follows the slot's live
   color) is how dream weather has always worked; Lumen leans on it
   harder (bands, chase, conduct). If firmware matches static twins
   first, the band base hexes are single-LSB-adjustable.
3. **`frame.imu_data()` fields/units** — parallax is pcall/nil-guarded
   and EMA-normalized, but `PAR_RATE_GAIN` assumes degrees; recalibrate
   with one on-device session (the raster stub makes the logic testable
   today).

## Revision log

- 2026-07-03 — Initial Lumen pass (engines, horizon, focus, five cards,
  hero moments, prism rebuild + visibility fix).
