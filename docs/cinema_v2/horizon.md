# The Horizon

*(Status 2026-07: shipped with Phase 3 geometry retunes — marks lengthened
to 3/6/9px by tier, notch breathe 6→9px, rim anchor `MER_RIM_R = 105`; the
smaller figures below are the Phase 2 values. See
`docs/CINEMA_V2_PROTOTYPE_REVIEW.md`; `display/animations.lua` `MER_*` is
authoritative.)*

## Pitch

The resting display is the wearer's day drawn as a thin ring of marks at
the rim — one mark per remembered event, placed at the hour it happened.

## Information carried

- **Existence**: each mark is one event in the semantic ring buffer
  (`memory/ring_buffer.py`) — a memory, promise, or person moment.
- **Time**: the mark's angle is when it happened (past) or when it is
  due (promise, future side).
- **Kind**: mark glyph + color token (memory tick / promise dot /
  person pin).
- **Certainty**: mark luma tier (dim token vs full token) from event
  confidence.
- **Density**: clustered marks merge and lengthen — a busy hour is
  visibly heavier than a quiet one, with zero words.
- **Liveness**: the now-notch breathes; a breathing notch means the
  system is on and capturing (replaces the ReadyCard glyph's one bit).
- **Staleness**: if the host goes silent, marks drop one luma tier while
  the notch keeps breathing — "device alive, memory link stale" is
  visually distinct from both "all good" and "off".

If a mark carried nothing (kind unknown, confidence 0, no timestamp) the
composer drops it host-side; the device never draws a decorative mark.

## Sensors / state / events

- Host: `SemanticRingBuffer.since()` (`memory/ring_buffer.py:50-54`),
  `CommitmentDriftEngine.all_records()`
  (`orchestrator/commitment_drift.py:115-117`), place signatures for
  person/place kinds. Composed by
  `orchestrator/horizon_composer.py` (new), streamed as `{t:"horizon"}`
  (see `horizon_frame.md`).
- Device: `halo-lua/display/horizon.lua` holds the last frame; renders
  every tick in Memory Mode idle and (dimmed) in Dream Mode.
- Events: none directly — the horizon is pure presentation. Gestures
  keep their v1 meanings.

## Geometry (all constants in `display/animations.lua`, `MER_*`)

- Dial: **30° per hour** (full circle = 12h). Screen coords, y down:
  now = −90° (12 o'clock). Past sweeps **clockwise** (a memory from 3h
  ago sits at 0° = 3 o'clock). Future (promise due times) sweeps
  counterclockwise from now (due in 3h = 180° = 9 o'clock).
- Caps: lookback and lookahead **5h each** (150°). The bottom arc
  between +60° and +120° is the **seam** — permanently empty; past ends
  on its right edge, future begins on its left. Overflow: events older
  than 5h merge into one dim *elder tick* at +58°; promises further out
  collapse to one dot at +122°.
- Rim band: marks live at r ∈ [100, 108] (`MER_RIM_R = 104`), fully
  inside the 112px safe radius, outside the focus ring layer (r=92) and
  card content.
- Marks:
  - memory = radial tick from r=102 outward, length 2/4/6px by luma
    tier (`MER_MARK_LEN`), color `accent_memory_dim` (dim tier) or
    `accent_memory` (full tier).
  - person = 2px tick capped with a 1px dot at r=107 ("pin"),
    `accent_memory`.
  - promise = dot at r=104 in the amber family — full state grammar in
    `promise_arc.md`.
  - merge rule: marks within 3° (`MER_MARK_MERGE_DEG`) collapse into
    one tick, +1px length per absorbed mark (cap 8px).
  - cap: 48 marks (`MER_MARKS_MAX`); composer drops lowest-confidence
    memories first, never promises.
- Now-notch: 2px radial tick at −90°, r 100→[104..107]; length breathes
  4→7px (`MER_NOW_LEN_MIN/MAX`) on `BREATHE_CYCLE_MS` (3200ms),
  `in_out_sine`. Geometric breathe — no palette slot consumed.

```
                        now-notch (breathes)
                       ┃
              future ╱ ┃ ╲ past
        promise ●     ┃      ' mem tick (dim)
       (due 2h)          .       | mem tick (bright)
                                  |
    ●  promise                       ' person pin º
   (cracking,                        |
    slipped in)                    ' '   <- merged cluster (long tick)
              ╲                 ╱
                '─ ─ seam ─ ─'
              (empty by design)
```

## Behavioral spec

- Render order in idle: horizon (Air/Ghost) → nothing else. During
  focus: horizon stays, at one luma tier lower, under the focused card.
- Frame updates: on `{t:"horizon"}` arrival, marks snap to new angles —
  no tweening (angular drift is ≤0.5°/min; snapping is invisible).
  Stale rule: if no frame for 30s (`MER_STALE_MS = 30000`), drop all
  marks one luma tier.
- Marks never rotate device-side; angles come from the host frame.
  The device is a dumb plotter — no clock math on the Lua side, so
  clock skew cannot shear the dial.

## reduce_motion

The horizon is already ~static. The only motion is the now-notch
breathe and the arrival pulse (`focus.md`); under reduce_motion the
notch is a fixed 6px tick and arrival pulses render as a single-frame
luma step. All positional information is identical.

## Failure modes

- **Empty buffer (new device, fresh morning)**: notch + seam only. This
  is correct and honest — "nothing remembered yet." The notch alone is
  the on-signal.
- **Host link stale**: marks −1 luma tier; notch unaffected (device
  liveness ≠ memory liveness).
- **Uncertain events**: low confidence = dim short tick; below the
  composer floor (conf < 0.30) not sent at all.
- **Contradicted / revoked memory** (forget-last, purge): composer
  omits it on next frame; mark vanishes without ceremony — deletion is
  silent by design (no tombstones for forgotten things; privacy).
- **Privacy Veil**: composer stops sending; device draws notch in
  `status_paused` and *no marks* while paused — paused state is
  unmistakable at the rim, matching PrivacyVeilCard center-stage.

## Peripheral-glance test (400ms, no focus)

Readable without foveating: (1) system on (notch breathing), (2) busy
vs quiet day (mark density right of top), (3) promise pressure
(amber presence left of top), (4) anything slipping (a dot off the rim
band, `promise_arc.md`). Not readable, by design: which specific
memory a tick is — that requires focus (a query), which is the point.

## Daily-use test (day 30)

The horizon resists wallpapering because its content *is* the day —
it is different every hour by construction, the way a watch face is.
The specific day-30 protections: marks are capped, ghost-tier, and
1–6px so the rim never becomes a field of noise; the seam guarantees
permanent negative space; and the only permanently-repeating element
(the notch) is the smallest thing on screen. The wearer who stops
noticing individual ticks still reads density and amber pressure
pre-attentively — that reading is the product.

## Reality Compiler note

Meridian adds no user-programmable behaviors, so no new RC intents are
required; the RC constraint is satisfied vacuously. A running figment
still owns the whole display (`main.lua` render priority unchanged) —
the horizon yields, exactly as v1's cards did.
