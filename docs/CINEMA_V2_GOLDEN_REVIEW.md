# Cinema v2 — Golden Review

Phase 5 record. Every Meridian element was rendered **through the
integrated device code** (`display/renderer.lua`, `horizon.lua`,
`focus.lua`, `dream_renderer.lua`) on a controlled clock via the raster
harness, exported to `assets/cinema_v2/golden/<element>/<state>.png` by
`hud/export_cinema_v2_golden.py`, and inspected across three passes.
Animated states are committed as frame sequences (condense/recede/
testimony-enter). The v1 sample set (`assets/hud/samples/`) was also
regenerated — it now includes the three cards whose goldens were black
discs, and the recolored confidence family.

Method note: pass N means "the whole set was re-inspected after the
fixes from pass N−1 were applied and everything re-exported." Where a
pass found nothing, the specific things checked are named — a pass that
finds nothing must prove it looked.

## What the passes changed (chronological)

**Pass 1 findings:**

1. `focus/reduce_motion_hold.png` was a **mislabeled travel frame** —
   the exporter set the transitions flag directly, but
   `renderer.show_card` re-reads `settings.reduce_motion` on every
   ENTER and silently overwrote it. The golden showed a condensation
   head, not the reduced hold. Fixed by driving
   `system.settings.set("reduce_motion", true)` — the same path the
   device uses. This is exactly the class of lie (a golden that
   certifies the wrong state) the v1 judgment documented; caught here
   because the state name and the pixels disagreed on inspection.
2. `weather/dream_storm.png` was **sub-visibly stormy** — the palette
   shifts chosen for the golden were too mild to read as a mood change.
   Storm-strength YCbCr shifts applied; quiet vs storm is now
   unmistakable side by side.
3. The testimony sessions had **no day under the verdict** (empty
   horizon). The paradigm says the terrain never cuts away; the
   exporter now feeds the day frame first. All three testimony states
   re-exported with the rim present.
4. **The violet died.** `hold_conf090.png` showed v1's
   `confidence_high = 0xAA00FF` jewel orbits clashing against the teal
   focus ring — the exact off-family collision the v1 risk register
   flagged and shipped anyway. Decision (v2's to make, and made):
   `confidence_high` is now `0xB8FFE9` — the brightest member of the
   teal family; highest confidence reads as *most light*, not as a
   foreign hue. Applied in `palette.lua`, `themes.py`, `colors.ts`;
   every affected golden regenerated.
5. **A real device bug, found by the pixels:** exporting the anchor
   echo crashed the harness on a broken UTF-8 byte — v1's
   `ghost_wake_text` iterates *bytes* (`text:sub(i,i)`), so the
   "• MEMORY ECHO •" bullets the anchor renderer actually sends were
   being sliced into three garbage draws per bullet on the device too.
   Fixed with a UTF-8-aware character split in `transitions.lua`. The
   golden pass paid for itself with this one.

**Pass 2:** full re-inspection after the five fixes. `reduce_motion_hold`
now shows content + full-sweep ring + origin tick in one static frame
(the parity contract, visible). `dream_storm` reads charged.
`clean_truthful` is one quiet green ring around CONSISTENT with the day
at the rim — boring on purpose; that is what "nothing is wrong" should
cost. No new defects; the specific things looked for: state/pixel
agreement on every filename, ring-vs-track separation, capsule-vs-thread
collision (none at r=64), notch presence in every frame, seam emptiness.

**Pass 3:** final sweep of the states not re-touched since pass 1 —
`promise_arc/*` (the five-state ladder, radial stack, and fractured
shattered tick all arrive **through the wire codec**, proving the
horizon-frame round trip, not just the drawing), `recede_complete_pulse`
(the origin mark visibly pulses when the content lands home),
`anchor_echo` (bullets render correctly post-UTF-8-fix; the anchor's
mark at −30° is lit while the echo shows), `testimony/enter_*` (verdict
first, evidence accumulating in stage order). No remaining critiques at
this altitude; accepted residuals below.

## Per-element verdicts

**Horizon** (`horizon/idle_day|idle_empty|idle_paused|idle_stale`) —
the resting display is a legible instrument: track, seam, morning
cluster, person pin, two promises, breathing notch. `idle_empty` reads
as "instrument at rest," not "dead display" — the ReadyCard glyph is
survived by something that actually says things. Accepted residuals:
`idle_stale`'s one-tier drop is only obvious next to `idle_day` (the
in-frame cue is mark-vs-notch contrast; the temporal signature — marks
visibly stepping down after 30s — doesn't exist in stills); the elder
tick stays a deliberate whisper.

**Focus** (`focus/condense_t*|hold_conf*|recede_t*|recede_complete_pulse|
reduce_motion_hold`) — the two-phase grammar is legible in stills:
departure from the lit origin mark, landing ring gating staggered
content, static ring with sweep = confidence (324° vs 72° is a
pre-conscious read), text cut during recession, arrival pulse on the
mark. Accepted residuals: v1's ObjectRecall content (rail + bezier +
jewel) is busy over the dial at top-left — card *content* redesign is
explicitly out of v2's scope (the judgment's Wrong #3 honorable mention
stands for a future pass); at conf ≥ 0.9 the ring's unswept gap sits
near the notch angle — 8px of radial separation (92 vs 100) was
verified adequate in the stills.

**Promise Arc** (`promise_arc/ladder|stacked|shattered_past`) — five
states countable in one glance, three same-hour promises countable as
three, and the fracture is findable in one scan. These frames came in
as `{t="horizon"}` payloads: codec, cap and stacking logic are what's
actually being certified here.

**Testimony Thread** (`testimony/*` + `enter_t*`) — ELEVATED with two
early tears and one honest gap reads in one fixation;
`stranger_insufficient` is a compass rose of ignorance around UNKNOWN
(correct and slightly unsettling); the enter sequence shows headline
first, evidence second. The backing capsule never touches the thread at
r=64. Accepted residual: the harness font is heavier than device glyphs
(conservative direction — text that survives here survives there).

**Weather** (`weather/dream_quiet|dream_storm|anchor_echo`) — same
terrain, different light is visible: marks at floor tier, promises
still amber, notch breathing, field bending around the rim, particles
held inside r=96. Known harness caveat, stated plainly: the raster
resolves any draw whose color equals a dynamic slot's *base hex* to the
slot's live color, so v1's particles (drawn in the static
`accent_memory` token, which is also the energy slot's base) show
storm-shifted in the golden while on device they stay static. The
golden slightly *overstates* the storm; the understated direction would
have been the dangerous one. Logged in `CINEMA_V2_RISKS.md`.

## The anti-black-frame contract

Every committed golden in `assets/cinema_v2/golden/` was inspected as
pixels, and Phase 7 adds the regression the v1 pipeline never had:
`test_cinema_v2_golden.py` asserts every golden in the tree has a
non-trivial lit-pixel count — a black disc can never again be certified
as "passed inspection."
