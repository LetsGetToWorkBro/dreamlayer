# Halo Cinema v1 — Design System Upgrade

> DreamLayer's motion, material, and hierarchy language for Brilliant Labs Halo.
> Successor to the "premium and calm" pass. One atomic upgrade: renderer,
> dream engine, card library, phone companion.

Hardware ground truth (non-negotiable):

- 256×256 **circular** color display, 16px safe inset (`lib/constants.lua: SAFE_RADIUS = 112`)
- **16-color 4bpp indexed palette** — "opacity" only exists as palette slots;
  animated via `frame.display.assign_color_ycbcr(idx, y, cb, cr)` (0–1023 each)
- BLE MTU **240 bytes**; sprites chunked by `brilliant-msg`
- ~**20 fps** display ceiling (50ms tick), **2 Hz** host dream tick
- Renderer primitives only: `frame.display.line/rect/circle/text/bitmap`
- Every color = semantic token (`display/palette.lua` / `hud/themes.py`)
- Every duration = named constant (`display/animations.lua`)
- Every motion honors `settings.reduce_motion`

---

## 1.1 Motion language — six named signatures

All signatures live in `halo-lua/display/transitions.lua`, timing constants in
`display/animations.lua` (`A.SIG_*`), easing in `lib/easing.lua`.
`renderer.lua` routes each card type to its declared signature via the
`SIGNATURES` table; per-card draw functions stay pure (they draw a fully-held
card) and the signature modulates *how* that drawing is revealed, held, or
dismissed.

### S1 — Iris Bloom (card ENTER — default)

**Emotional intent:** an answer *surfacing* from memory, not a window opening.
**Replaces:** the 180ms scale-fade (`ENTER_SCALE_FROM 0.94`).

Mechanism: a radial mask reveal. An outer ring (accent-colored, 1px arc)
collapses from the safe-area edge (r=112) inward toward the content radius
(r=36) while content layers draw on *inside* the collapsing radius. Since 4bpp
has no alpha, the "fade up" of inner content is a palette ramp: the ghost-tier
slot assigned to entering text is animated Y 160→640 over the trailing 60ms
via `assign_color_ycbcr`.

```
frame 0ms          frame 90ms         frame 180ms        frame 240ms
.--~~112~~--.      .--~~74~~--.       .--~36~~--.        (ring gone)
|  (empty)  |      |  eyebrow  |      | eyebrow  |       eyebrow
|     o     |      |  PRIM..   |      | PRIMARY  |       PRIMARY
|           |      |           |      | detail   |       detail
'-----------'      '-----------'      '----------'       footer
 ring @ edge        ring collapsing    ring lands,        ghost slot Y
                    content inside     content full       ramp completes
```

| Param | Value | Constant |
|---|---|---|
| Ring collapse | 112px → 36px, 180ms | `SIG_IRIS_MS`, `SIG_IRIS_R_FROM/TO` |
| Ring easing | `out_expo` | `EASE_ENTRANCE` |
| Content trailing edge | 60ms Y-ramp on ghost slot | `SIG_IRIS_TRAIL_MS` |
| Layer stagger | 0/40/60/80ms (kept) | `STAGGER_*_MS` |
| Palette slots | 1 ghost-tier slot (`ghost_text`) | `palette.reserve_dynamic` |

Primitive decomposition: `arc(CX,CY,r,0,360,accent)` per frame with
`r = lerp(112,36,out_expo(t))`; text/glyph draws are gated by
`r_current >= element_radius` instead of the old uniform scale.

### S2 — Ghost Wake (WorldAnchorCard ENTER)

**Emotional intent:** a memory condensing out of the ambient field — it was
always there, it just became legible.

Mechanism: each character of the anchor text is drawn individually with a
per-character offset sampled from a Perlin-lite curve seeded by monotonic
time + char index. Offsets converge ±2px → 0 over 320ms while the ghost-tier
palette slot ramps Y from 0 → `text_ghost` luma.

```
frame 0ms          frame 110ms        frame 220ms        frame 320ms
 M  e M o r Y      M e M o r y        M e m o r y        Memory echo
  jitter ±2px       jitter ±1.3px      jitter ±0.5px      settled, ghost
  Y = 60            Y = 210            Y = 330            Y = 400 (ghost)
```

| Param | Value | Constant |
|---|---|---|
| Duration | 320ms | `SIG_GHOSTWAKE_MS` |
| Jitter amplitude | 2px → 0, `in_out_cubic` decay | `SIG_GHOSTWAKE_JITTER_PX` |
| Noise | `easing.perlin1d(seed + i*7.13)` | — |
| Opacity ramp | ghost slot Y 0→400 | `SIG_GHOSTWAKE_Y_FROM/TO` |
| Palette slots | `ghost_text` dynamic slot | — |

### S3 — Prism Slide (card→card crossfade)

**Emotional intent:** the old thought doesn't die, it *refracts* out of focus
as attention moves.

Mechanism: the outgoing card's accent color slot is temporarily split: the
outgoing card is drawn twice at ±2px horizontal offset; pass one draws with
the dynamic slot pushed Cb+96 (cool fringe, right), pass two with Cr−96
(warm-negative fringe, left) — a chromatic split done entirely with
`assign_color_ycbcr` on the reserved `prism` slot, no extra colors consumed.
Over 140ms the fringes converge and Y falls to 0 while the new card irises in
(S1) simultaneously.

```
frame 0ms            frame 70ms            frame 140ms
 OLD CARD             O̲L̲D̲ ̲C̲A̲R̲D̲             (gone)
 (sharp)              ↞2px cyan / 2px→      new card iris
 new: ring @112       warm split, dimming   lands @36
```

| Param | Value | Constant |
|---|---|---|
| Duration | 140ms | `SIG_PRISM_MS` |
| Chromatic offset | ±2px | `SIG_PRISM_SPLIT_PX` |
| Cb push / Cr pull | +96 / −96 | `SIG_PRISM_CB`, `SIG_PRISM_CR` |
| Outgoing Y ramp | base → 0, linear | — |
| Palette slots | `prism` dynamic slot | — |

### S4 — Confidence Halo (HOLD idle for recall cards)

**Emotional intent:** confidence you *feel* before you read. Replaces the
breathe pulse on ObjectRecall / CommitmentRecall / ProactiveMemory /
PersonContext.

Mechanism: a 1px orbital arc traces the card's circumference once per 3.2s.
Arc **radius** = `24 + confidence × 40` px; arc **sweep length** =
`confidence × 360°`. High-confidence answers wear a long, wide halo; shaky
ones a short, tight one. Arc color = existing `conf_color` mapping.

```
conf 0.9:  ( ═══════════╗ )   sweep 324°, r=60   — nearly closed crown
conf 0.5:  (      ══════  )   sweep 180°, r=44   — half halo
conf 0.2:  (        ══    )   sweep  72°, r=32   — a worry-flicker
```

| Param | Value | Constant |
|---|---|---|
| Orbit period | 3200ms | `SIG_HALO_PERIOD_MS` (=`BREATHE_CYCLE_MS`) |
| Radius | 24 + conf×40 px | `SIG_HALO_R_BASE`, `SIG_HALO_R_CONF` |
| Sweep | conf×360° | — |
| Stroke | 1px arc, 24 segments | — |
| Palette slots | none (static conf colors) | — |

### S5 — Truth Ripple (Truth Lens result ENTER)

**Emotional intent:** a verdict *lands* somewhere — at the eye that produced
the tell — and the world absorbs it.

Mechanism: when deception score ≥ threshold, a ripple (2 concentric 1px
circles, 12px apart) originates at the card's `origin` anchor (eye landmark
projected to display coords; falls back to (128,96)) and expands to r=120 over
400ms. Simultaneously the reserved `ripple` slot warm-shifts Cr +0→+80 and
back (palette warm pulse). Then the card settles into ambient breathe. If the
user dismisses a low-confidence/false-positive verdict, a single *cold* ripple
(Cb +60, 240ms) plays — recovery reads as cooling.

```
frame 0ms          frame 130ms        frame 270ms        frame 400ms
    ·eye              (  ·  )            ((  ·  ))           card settles
  r=0, Cr+0          r=38, Cr+64        r=84, Cr+40         r=120→gone, Cr+0
```

| Param | Value | Constant |
|---|---|---|
| Duration | 400ms | `SIG_RIPPLE_MS` |
| Radius | 0 → 120px, `out_quad` | `SIG_RIPPLE_R_MAX` |
| Warm shift | Cr +80 peak @ t=0.33 | `SIG_RIPPLE_CR` |
| Cold recovery | Cb +60, 240ms | `SIG_RIPPLE_COLD_MS`, `SIG_RIPPLE_CB` |
| Palette slots | `ripple` dynamic slot | — |

### S6 — Memory Comet (ProactiveMemoryCard ENTER)

**Emotional intent:** this memory *traveled* to reach you — and how far it
traveled is when it's from.

Mechanism: a single 2px lit pixel enters from the display edge and follows a
quadratic bezier to the card's primary text anchor over 280ms, leaving a
3-sample fading tail (previous 3 positions drawn as 1px dots in
ghost/dim/trace shades). **Entry angle encodes recency**: 12 o'clock = today,
each week older sweeps +30° clockwise (capped at 330°). On arrival the card
irises in (S1) from the impact point.

```
recency=today  → enters at 90° (top);  recency=6wk → enters at 270° (bottom)

frame 0ms          frame 100ms        frame 200ms        frame 280ms
   *·              .                  .                  card blooms
    (edge)           *··                 ~~*··             at anchor
```

| Param | Value | Constant |
|---|---|---|
| Duration | 280ms | `SIG_COMET_MS` |
| Path | bezier(edge, ctrl, anchor), `in_out_cubic` | — |
| Tail | 3 samples, ghost→dim→trace | `SIG_COMET_TAIL` |
| Angle | 90° − weeks×30° (clockwise) | `SIG_COMET_DEG_PER_WEEK` |
| Palette slots | none | — |

**Exit (all cards):** unchanged 120ms contract, but routed through
`transitions.exit_contract` so Prism Slide can replace it during crossfade.

---

## 1.2 Material system — Air / Ghost / Solid

Every drawn element belongs to exactly one tier. `display/materials.lua`
owns the rules; the tier decides which palette slots and dither patterns an
element may use. Since 4bpp has no alpha, "opacity" is faked two ways:
**(a)** dedicated ghost-tier palette slots whose Y/Cb/Cr the host or device
animates, and **(b)** ordered-dither skip patterns for area fills.

| Tier | Role | Slots | Dither | Examples |
|---|---|---|---|---|
| **Air** | ambient field, never information-bearing | dynamic slots 1–4 (`sky`, `energy`, `drift_a`, `drift_b`) | `DITHER_25` (1-in-4 checker) | dream particles, line field, iris ring residue |
| **Ghost** | present-but-not-primary information | dynamic slots 5–6 (`ghost_text`, `prism`/`ripple` shared) | `DITHER_50` (checker) | WorldAnchor echoes, footers, breadcrumbs, exiting cards |
| **Solid** | the one thing that matters | static palette (text_primary, accents, conf colors) | none (full fill) | primary line, verdict word, confidence jewel |

Slot reservation contract (`palette.reserve_dynamic(name, base_hex)`):

- Slots **0** (background) and **7–15** (static semantic colors) are never
  reassigned at runtime.
- Slots **1–6** are the dynamic bank. `reserve_dynamic` hands them out by
  name (idempotent: same name → same slot) and records the base color so
  `palette.restore(name)` can snap back after an animation.
- Host mirrors the same slot map in `hud/themes.py: DYNAMIC_SLOTS` so
  `{t:"palette"}` frames and on-device animations never fight over a slot.

Dither patterns are compile-time constant tables of `{dx,dy}` offsets applied
when stamping area fills; text is never dithered (it garbles glyphs at 10–13px)
— ghost text uses the ghost slot's luma instead.

---

## 1.3 Sound of silence — HUD acoustics analog

Halo has no speaker. Each "sound" maps to exactly one renderer function:

| Acoustic event | Visual analog | Renderer function |
|---|---|---|
| **Chime** (memory saved) | single 1px ring, r 8→28, 220ms, out_expo, accent_success — one clean overtone | `transitions.chime(cx, cy)` |
| **Chord** (person recognized) | three arcs (r 32/40/48) light in 3×40ms arpeggio around the avatar halo, then hold | `transitions.chord(cx, cy, conf)` |
| **Sub-bass rumble** (privacy veil) | full-field 2-frame dim: dynamic slots 1–6 Y −160 for 100ms, then shield slam proceeds — the room gets quieter before the door shuts | `transitions.rumble()` |
| **High shimmer** (proactive surface) | Memory Comet's tail widens 1px for its final 80ms — arrival sparkle | built into `transitions.comet` |

---

## 1.4 Accessibility contract (`settings.reduce_motion`)

Every signature must preserve its **information** without its animation:

| Signature | reduce_motion variant |
|---|---|
| Iris Bloom | card appears at once (single frame), staggered layers collapse to 0ms |
| Ghost Wake | text appears settled at final ghost luma, no jitter |
| Prism Slide | hard cut old→new, no chromatic split |
| Confidence Halo | **static** arc: same radius & sweep encoding, drawn once, no orbit |
| Truth Ripple | no ripple; verdict ring drawn complete, warm tint applied statically for 400ms then restored |
| Memory Comet | no comet; a static 8px tick mark at the encoded entry angle on the card rim preserves the recency reading |
| chime/chord/rumble/shimmer | single static frame of their end state |

`transitions.set_reduce_motion(bool)` is read once per card ENTER from
`system/settings.lua`; every signature function branches on it internally so
callers never need to.

---

## 1.5 Kill list

Removed or replaced — better five perfect signatures than fifteen mediocre ones:

1. **ENTER scale-fade (0.94→1 uniform scale)** — replaced by Iris Bloom.
   Scaling vector line-art by 6% at 256px just wobbles 1px lines; it read as
   jitter, not motion. `ENTER_SCALE_FROM/TO` kept only as deprecated aliases.
2. **EXIT scale-to-zero on text** — text shrinking to 0 via `floor()` produced
   two ugly frames of clipped glyphs. Exit now contracts *geometry only*;
   text cuts at t=0.4 (`transitions.exit_contract`).
3. **Breathe opacity pulse on recall cards** — replaced by Confidence Halo.
   The pulse carried zero information; the halo carries confidence.
4. **DeviationAlert hold ripple's fake alpha** (`alpha = 1.0 - rp` comment
   admitted the display can't do it; it modulated arc step count, which read
   as flicker) — replaced with a Truth-Ripple-style expanding ring that dims
   via the ripple slot's Y, which the hardware *can* do.
5. **`draw_low_confidence` triple-dot footer wobble** — static dots now;
   the card itself already says "Not sure".
6. **Dream `mode="scatter"` particle explosion** — head-shake made the field
   *explode*, the opposite of calm. Replaced by curl-noise damping
   (Line Field 2.0); scatter mode is accepted but mapped to a damped swirl.
7. **8-vector radial line field** — replaced by the 12-vector curl-noise
   field (§Phase 3), gyroscopically damped.
8. **`ghost_white = 0x08FFFFFF` pseudo-alpha hack** in palette.lua — the
   display has no ARGB. Deleted in favor of the ghost tier slot.

---

## Phase 3 addendum — Dream Mode upgrade contracts

- **Palette Weather** (`mic_reactor.py`): two-band emotional weather.
  Low band (FFT bins 0–8) = *pressure* → `sky` slot moves along **Cb**
  (quiet = deep cool blue, bass-full = storm blue-violet). High band
  (bins 9–31) = *energy* → `energy` slot moves along **Cr** (hiss/sibilance =
  warm ember). Y follows total amplitude. Slots `drift_a/drift_b` trail
  `sky`/`energy` by one tick for depth. Output stays `{t:"palette", colors:[4]}`.
- **Line Field 2.0** (`imu_reactor.py` → `{t:"line_field", v:[…12]}`):
  12 vectors from a curl-noise sample grid, rotated by damped yaw/pitch
  (critical damping, ζ≈1: head shakes shed 90% of their rate in one tick).
  Wire format: 12×4 int16-ish ints as JSON — ≤ 200 bytes, one MTU frame.
- **Scene→Sprite** (`scene_describer.py`): one VLM call returns
  `{"phrase": six words, "sprite": {"dominant": "#RRGGBB", "shapes":
  [{kind, x, y, size}, ×3]}}`; deterministic offline fallback derives both
  from a phrase-hash. `SpriteBridge` packs 128×128 @ 4bpp (~4KB < 8KB budget).
- **SynesthesiaCard v2**: sprite bottom-half, phrase top-half at ghost tier.
- **PlaceReactor** (`place_reactor.py`): known-safe place → `sky` biases
  toward accent_memory chroma; novel place → toward accent_attention, ramped
  over 8s. Ambient trust signal; output is a low-priority palette frame.

## Phase 4 addendum — lens presentation contracts

- **Truth Lens 9-ring gauge**: rings r=20…52 (3px pitch+stroke), one per
  stage (face, AU, voice, prosody, linguistic, narrative, fusion, aggregate,
  verdict). Ring fill = stage confidence × 360°, clockwise from 12 o'clock.
  Ring color by signal direction: `accent_success` truthful / coral
  `accent_attention` deceptive / `text_ghost` insufficient. Center: verdict
  word (Solid tier) + confidence dot. Entry = Truth Ripple from `origin`.
- **Social Lens result**: name PRIMARY; one line of "why this person matters
  right now" = highest-scoring memory mentioning them in last 30 days
  (via `memory/retrieval.py`); 32×32 cached avatar sprite ringed by a
  Confidence Halo. Avatar renders **only** for registered contacts — a
  non-contact result never carries a sprite (enforced in
  `social_lens/renderer.py` and tested).

## PROPOSED_DEPENDENCY

- `react-native-svg` (phone-app only). Justification: `CardPreview`/
  `DreamCanvas` need line/circle/rect/text parity with `frame.display`;
  RN core Views cannot draw arcs or beziers. ~200KB, zero network use,
  renders offline. No Python or Lua dependency changes. (`lupa` is added to
  the host **dev extras only** so the existing Lua-side pytest suites stop
  silently skipping; it never ships.)
