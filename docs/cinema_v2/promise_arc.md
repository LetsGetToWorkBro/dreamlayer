# The Promise Arc

*(Status 2026-07: shipped with revisions to the glyph table below — shattered
renders as a *fractured* tick (two segments with a gap, Phase 3), radial
stack pitch is 7px, anchors are r=105/slip 95, and the Lumen pass later added
bounded state micro-motion (blooming breathes, cracking trembles, a one-shot
shatter transition), superseding the "no device animation" rule. See
`docs/CINEMA_V2_PROTOTYPE_REVIEW.md`, `lumen.md`; `MER_PROMISE_*` in
`display/animations.lua` is authoritative.)*

## Pitch

Every open commitment is a mark on the future side of the horizon that
physically strains as its due time approaches and its drift state
decays — the wearer watches a promise start to slip a day before v1
would have shouted at them.

## Information carried

- **Existence & count**: one dot per open commitment (drift engine's
  live record set — `orchestrator/commitment_drift.py:115-117`).
- **Due time**: angle on the counterclockwise (future) side; due-in-2h
  sits 60° left of the notch.
- **Drift state**: the five-step ladder (`commitment_drift.py:7-12`)
  rendered as physical strain (shape/position/color), not as an alert.
- **Urgency direction**: radial position — a dot slipping *off the rim
  band inward* is losing integrity; the rim is where healthy things
  live.

## Sensors / state / events

- Host: `CommitmentDriftEngine.all_records()` on the composer tick;
  each record contributes `{angle from due_ts, state, kind=promise}` to
  the horizon frame. Records with no parseable due use the engine's
  48h-lifetime decay (`commitment_drift.py:102-108`) and sit at the
  future cap.
- Device: rendered by `horizon.lua` as part of the mark pass — no
  separate module; the Promise Arc is a *grammar*, not a widget.
- The one-shot CommitmentDriftCard alert (cracking/shattered) still
  fires exactly as v1 (`orchestrator.py:198-213`) — the arc is the
  ambient layer *under* the alert, not its replacement. When the alert
  card condenses, it condenses **from the slipping dot** (its
  origin_deg = the promise's angle): the interruption visibly comes
  from the thing you watched slip.

## Visual spec (state grammar)

| state | decay | glyph | r | color token |
|---|---|---|---|---|
| blooming | <0.20 | 1px dot | 104 | `confidence_low` (soft amber) |
| healthy | 0.20–0.50 | 2px dot | 104 | `confidence_low` |
| drifting | 0.50–0.75 | 2px dot + 2px inward stem | 104 | `warning_amber` |
| cracking | 0.75–1.00 | 2px dot, **slipped inward** | 96 | `warning_amber` |
| shattered | ≥1.00 | 3px fixed tick (r 94–99) | 96 | `status_paused` (cold) |

- State changes are **discrete redraws** on frame update — no device
  animation. A promise's decay advances over hours; tweening it would
  be theater. The *slip* from 104→96 happens between two horizon
  frames; its suddenness is the message.
- Shattered goes cold (blue-gray, not red): a broken promise is not an
  emergency, it is a fact. It stops moving forever (fixed tick) until
  the wearer addresses it (which removes or renews the record — the
  composer reflects whatever the engine holds).
- Passing the notch: an unresolved promise whose due time passes
  crosses to the past side like any other event — but as its shattered
  tick, so "that thing I didn't do at 2pm" is visible at 2pm's angle,
  aging clockwise with the rest of the day.

```
    future side                          state ladder (one promise, over a day)

     ● due 4h  (healthy, on rim)         09:00  ·      blooming, far left
    ●' due 90m (drifting, stem)          13:00  ●      healthy, sliding right
   .                                     16:00  ●'     drifting, stem grows
  ● <- cracking: slipped off rim         18:30   ●     cracking, slips inward
   `.                                    20:00   |     shattered: cold, fixed
     seam
```

## reduce_motion

Already motionless — the arc is discrete-state by design. The only
animated moment it participates in is the alert card condensing from
its dot (`focus.md` reduce rules apply there). Identical information in
both variants.

## Failure modes

- **Unparseable due** ("when you get a chance"): 48h decay, future-cap
  angle. Never dropped — a vague promise is still a promise.
- **Due beyond 5h**: collapsed dot at the future cap (+122°); it
  detaches and takes its true angle when it enters the window.
- **More promises than arc space** (a cluster of dots within 3°):
  promise marks never merge (each is an obligation); they stack radially
  instead — second dot at r=100, third at r=96, capped at 3 visible +
  the count is what the phone is for. Radial stacking is acceptable
  precisely because the future side is sparse for humans (few people
  hold >3 promises due the same hour).
- **Engine empty / no due promises**: future side empty. Correct;
  emptiness on the left is rest, and it makes any single amber dot loud.

## Peripheral-glance test (400ms)

Amber presence left of the notch = "I owe something soon" — readable
without foveating. A dot off the rim band = "something is slipping" —
the radial displacement is 8px, above peripheral vernier acuity at this
size. Which promise it is requires focus, by design (glance → query →
it condenses from that exact dot).

## Daily-use test (day 30)

The arc's day-30 value is *negative space*: an empty future side is
earned calm the wearer can trust, because they've learned that anything
owed would be visible there. The failure to avoid is guilt wallpaper —
a permanent amber smear from chronic overdue clutter. Two protections:
shattered marks go cold (they read as history, not alarm), and they age
into the past side with the day instead of accumulating on the future
side. The arc never nags; it just refuses to lie about what's owed.
