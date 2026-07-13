# The Testimony Thread

*(Status 2026-07: shipped with the thread at r=64, not the r=48 below — the
Phase 3 prototype pass found the verdict capsule erased the thread at r=48;
`TESTIMONY_R = 64` in `display/animations.lua` is authoritative. See
`docs/CINEMA_V2_PROTOTYPE_REVIEW.md`.)*

## Pitch

The Truth Lens verdict is one line that either holds, tears, or runs
out: the nine-stage analysis drawn as a single arc accumulating around
the verdict word — not nine nested rings the eye cannot separate.

## Information carried

Identical payload to v1's gauge (`card.stages[9]`, each
`{name, confidence, direction}` — `hud/cards.py:306-333`), re-encoded:

- **Stage order**: position along the thread (the pipeline is ordinal:
  face → AU → voice → prosody → linguistic → narrative → fusion →
  aggregate → verdict), clockwise from 12.
- **Stage confidence**: stroke length within the stage's fixed 40°
  slot (conf × 40°); the unfilled remainder of the slot is an honest
  gap.
- **Stage direction**: stroke style — truthful = continuous arc in
  `accent_success`; deceptive = **torn**: 3 short dashes with ±2px
  radial jitter in `accent_attention`; insufficient = no stroke (the
  slot's boundary ticks make absence-of-evidence visible, never
  hidden — v1's one good gauge idea, kept).
- **Aggregate**: total thread completeness ≈ the fused result at a
  glance; verdict word (Solid tier) + confidence dot in the center,
  unchanged.
- **Origin of the tell**: Truth Ripple (S5) survives as the entry — the
  ripple still lands from `card.origin` (the eye landmark). It carries
  real information (where the verdict came from) and had no altitude
  problem. The cold-ripple false-positive dismiss also survives.

## Sensors / state / events

Unchanged from v1: TruthLensCard payloads from the host truth_lens
pipeline; `origin` anchor; no new sensors, no new BLE types.

## Visual spec (constants in `display/animations.lua`, `TESTIMONY_*`)

- Thread radius: r=48 (`TESTIMONY_R`), 1px stroke.
- Slots: 9 × 40° (`TESTIMONY_SLOT_DEG`), clockwise from −90°. Slot
  boundaries: 1px radial ticks r 46–50 in `border_subtle` (ghost tier)
  — these give ordinal addressability (count tears: "second and fourth
  stage") without labels.
- Tear rendering: the stage's arc split into 3 dashes (each ~conf×40°/4
  long, 4° gaps), alternating radial offset −2/+2/−2px; color
  `accent_attention`. A tear is *jagged where truth is smooth* — the
  reading is textural, pre-attentive.
- Center: verdict word `text_primary` with the black backing capsule
  (v1's armor was correct — kept, `renderer.lua:752-756` behavior);
  confidence dot below (conf-color mapping unchanged).
- ENTER: Truth Ripple (400ms, unchanged) → thread accumulates stage by
  stage, 80ms per stage (`TESTIMONY_STAGE_MS`, 720ms total), so the
  wearer watches the pipeline testify *in order*. Verdict word appears
  with the ripple (primary stagger), before the thread — headline
  first, evidence second.
- HOLD: fully static (thread + verdict + dot). No orbit, no pulse.
- Focus-law interaction: TruthLensCard's ring at r=92 is **not drawn**
  — the thread is the card's confidence surface; two concentric gauges
  would be v1's disease back again.

```
        F  AU  V           ENTER timeline
      .--''--..            0ms      ripple from eye landmark (S5)
   N /          \ P        400ms    ripple lands; VERDICT visible
    |  ELEVATED  |         400-1120ms thread draws F->AU->V->P->L->N->Fu->Ag->V
   L \    •     / Pr        (80ms/stage, clockwise)
      `--..--''            hold     static
       Fu Ag V

   continuous green = truthful stage      - - jagged red = torn (deceptive)
   empty slot between ticks = insufficient evidence (shown, not hidden)
```

## reduce_motion

No ripple (v1 rule kept: verdict ring statically warm-tinted 400ms then
restored); thread drawn complete on first frame. All tears, gaps and
lengths identical — the encoding never depended on the motion.

## Failure modes

- **stages missing entirely** (malformed card): verdict word + 9 empty
  slots — visibly "a verdict with no testimony," which is exactly the
  right amount of alarming.
- **Partial stages** (pipeline timeout): reported stages draw; the rest
  stay empty slots. Absence is rendered, never faked.
- **All-insufficient** (stranger, no baseline — fusion confidence
  pinned at 0.2 per `truth_lens/fusion.py:150`): thread is 9 empty
  slots + a sliver; the card reads as "we know almost nothing," the
  honest output for a non-contact (privacy floor respected: no
  baseline, no claim).
- **Low-confidence dismiss**: cold ripple (Cb-shift, 240ms), unchanged.

## Peripheral-glance test (400ms)

Three readings without foveating: verdict word (largest solid element),
thread completeness (mostly-full vs sparse), tear presence (red jag vs
smooth green — hue + texture double-coded). Which stage tore requires a
fixation to count ticks; that is deliberate — stage identity is a
second-glance reading, and the full named-stage table lives on the
phone (`CardPreview` mirrors the thread; the phone list names stages).

## Daily-use test (day 30)

The gauge's day-30 failure was noise: nine rings' worth of ink for
every verdict, however boring. The thread's ink is proportional to
evidence — a clean truthful read is one quiet green arc; drama appears
only when testimony tears. On day 30 the wearer has learned the two
shapes that matter (smooth-and-closed vs torn-early) and gets them in
one fixation; everything else has receded into texture. The element
earns its screen time by costing almost none when nothing is wrong.
