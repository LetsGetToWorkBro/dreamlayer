# Meridian Solid — every settled frame worth a screenshot

## The claim

Lumen made the light move; Solid makes the still frame rich. The founder
test for this pass was blunt: "from my end the screenshots don't look
that much different." All of Lumen's quality is temporal — springs,
flowing palette light, parallax — and the settled poses were
deliberately kept near-identical. Solid is the static half: real
typographic hierarchy, translucent material, gradient light, and
recomposed hero cards, all within the same call budget and the same
information-bearing discipline. A regression to the austere look now
breaks CI (the richness floors below).

## The three levers (all verified in code before design)

1. **Real font sizes.** `frame.display.set_font(fid, sz, sc)` existed in
   the adapter the whole time and was wired nowhere — every string on
   the glasses rendered at one size while the Python mirror pretended
   there were five. `typography.DEVICE_FONT` is now THE hardware seam
   (one table to recalibrate on glass); `primitives.set_font_size` is
   cached per size and pcall-latched — firmware without set_font
   degrades the whole feature to single-size text by flipping one
   boolean. `fit_size(text, width, ladder)` drops long hero strings to
   xl/lg instead of clipping the circular panel. The old `AVG_W` table
   equated font px with glyph advance (~2× too wide);
   `test_typography_metrics.py` pins the corrected advances to the
   reference face within ±2px.
2. **Cheap translucency.** Row-gap scanline fills: one `line` call per
   ROW. A r=62 glass disc at 3px gap = 41 calls; per-pixel dithering
   would be thousands and stays banned for areas. This is not the
   rejected set_pixel/moiré item from lumen.md: cost is per-row, and it
   is static, not temporal.
3. **Free static gradients.** Strokes whose segment color walks a token
   ramp — identical call count to a plain stroke.

## Materials API (`display/materials.lua`, twins in `hud/renderer.py`)

| Function | Cost | Notes |
|---|---|---|
| `glass_disc(cx,cy,r,color,gap)` | ⌊2r/gap⌋ lines (r62/g3 = 41) | circular clip, 2px inset, default `PANE` |
| `glass_capsule(x,y,w,h,color,gap)` | ≈h/gap lines | rounded-end inset |
| `grad_line(...,ramp)` | #ramp lines | |
| `grad_arc(...,ramp,steps)` | steps lines | == plain arc |
| `grad_bezier(...,ramp,steps)` | steps lines | continuous — the ramp replaces the 7/12 dash fake-alpha |
| `bloom_ring(cx,cy,r,color)` | 2 circles | dim twin at r+2, border at r+5 |

Ramps: `RAMP_MEMORY`, `RAMP_MEMORY_LIVE` (band bases first — the Lumen
conduct wave still flows on the bright half), `RAMP_SUCCESS`. New tokens
(`palette.lua`/`themes.py`): `accent_memory_static 0x2CC79B` (the fx
slot's base is `accent_memory` — static ramps must never use it, or the
geometry would follow live slot luma; same for `text_ghost`), plus
success/attention/amber dim twins. The alias-guard test asserts no new
hex equals any reserved dynamic base and no ramp contains one.

Rules: panes only in surface-luma colors (additive display — richer,
not brighter); panes and fills draw only when `exit_t == 0` (bounds the
crossfade worst frame and makes recession read as "the light files
first"); text never in pane color; privacy-class cards get no pane.

## The recompositions

- **ObjectRecall v3 — a spatial scene.** The place is a translucent
  field; the object is a layered diamond jewel with orbit arcs and
  bloom; the wearer is a dot at the bottom; a continuous gradient trace
  (dim at you, bright at the jewel) connects the two. Place name in hero
  type. The card *shows* where the thing is instead of listing rows.
- **SavedMemory v2 — a jewel.** Giant double-struck check inside
  concentric gradient rings over a soft pane; SAVED in hero type. The
  Lumen spring draw-on, chime, and burst contracts are untouched.
- **TruthLens — the verdict weighs what it claims.** Hero-class verdict
  in a glass capsule with a rounded outline; the thread gains *recency*:
  only the newest revealed stage is bright, older testimony cools to its
  dim twin — temporal order becomes a visible bit, direction hue is
  preserved.
- **PersonContext — a centerpiece.** Avatar ring with bloom under an
  enlarged crown over a pane; name in hero/xl; gradient separator; the
  one-why-line spec and chord arpeggio kept.
- **Material pass on the rest**: the live chain link glows from within
  (capsule fill) with gradient connectors; ReadyCard's inner ring is a
  gradient stroke; drift/scrub/deviation/proactive/loading information
  dots get bloom halos. The Horizon is identity and stays untouched
  except one bloom dot at the heartbeat tip.

## Budgets (measured by test_draw_budget.py, not estimated)

Worst composited frames — idle aurora, ObjectRecall/SavedMemory/
PersonContext holds, testimony all-9-stages, the ObjectRecall→Saved
crossfade, prism at max intensity — all measured ≤ `DRAW_CALLS_MAX =
420` (unchanged from Lumen). Font switches ≤ 32/tick (`font_calls`,
counted separately from draw calls, like palette writes).

## Richness floors (test_meridian_solid.py)

Regenerated goldens/samples must exceed the pre-Solid lit-pixel
baselines by ≥1.25×: `focus/hold_conf090` 3487→>4358,
`testimony/elevated_mixed` 1317→>1646, samples `object_recall`
3261→>4076, `saved_memory` 1436→>1795, `person_context` 1750→>2187.
"The screenshots don't look different" is now a CI failure.

## reduce_motion contracts

The settled composite is not pixel-identical across the flag — the
notch heartbeat freezes and reduce deliberately draws a static origin
tick in place of the travel motion. The two honest assertions, both
tested per recomposed card: under reduce_motion NOTHING moves (settled
frames at different times are pixel-identical), and the Solid materials
survive it (panes/gradients/blooms are static richness, not motion —
the reduce frame keeps ≥80% of the full frame's light).

## Device-day risks

1. **DEVICE_FONT calibration** — fid/sz/sc are one table; if firmware's
   set_font maps differently only the table changes; if it's absent the
   pcall latch reverts to single-size text with no other code path.
2. **PANE luma vs daylight** — `surface 0x0E1416` may be sub-visible
   outdoors on the additive panel; it is one token, tunable on glass
   (the same class as the aurora amplitude risk in lumen.md).
3. **Draw-color→slot resolution** — Solid leans on the same convention
   dream weather has always used; the band/twin hexes are single-LSB
   adjustable if real firmware matches static palette entries first.

## Revision log

- 2026-07-03 — Initial Solid pass (typography, materials, five
  recompositions, material pass, richness/stillness contracts).
