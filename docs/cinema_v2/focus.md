# Focus (Condensation / Recession)

*(Status 2026-07: shipped as specced, with later retunes — `SIG_RECEDE_MS`
is now 200ms (Lumen pass, see `lumen.md`; the 160ms below is the Phase 2
value) and the travel/landing gained spring physics. `display/animations.lua`
is authoritative for all constants.)*

## Pitch

One motion law replaces four signatures: things are drawn inward into
focus from where they live on the horizon, and go home when released —
nothing materializes, nothing dies.

## Information carried

- **Temporal origin**: the condensation path starts at the focused
  thing's time-angle — an answer from yesterday afternoon arrives from
  yesterday afternoon. The approach *is* the metadata.
- **Confidence**: the landing ring stays at the content edge with
  sweep = confidence × 360°, clockwise from 12 o'clock. (Iris Bloom and
  Confidence Halo unified; the orbit is dead, the encoding is not.)
- **Continuity**: recession visibly returns content to its mark — the
  wearer sees *where the thought went*, so dismissal teaches the
  geography instead of erasing evidence.
- **Focus state**: ring present = something is held; ring absent =
  ambient. One glance disambiguates mode.

## Sensors / state / events

- Driven by `renderer.show_card` / `renderer.dismiss` /
  `card_queue.tick` exactly as v1 — no new events.
- New card field `origin_ms` (host-stamped event time) → the device
  derives nothing; the host sends `origin_deg` precomputed in the card
  payload. Cards without a temporal origin (Error, Loading,
  QueryListening, Privacy) condense from −90° ("from the present").

## Visual & behavioral spec (constants in `display/animations.lua`)

Phase machine per card (replaces v1's enter/hold/exit):

```
        show_card(card)
              v
  [CONDENSE 240ms] --> [HOLD] --dismiss/expire--> [RECEDE 160ms] --> mark
        travel 140         ring stays                 text cuts t=0.4
        landing 100        sweep = conf               arrival pulse 300ms
```

- **Condense — travel (140ms, `SIG_FOCUS_TRAVEL_MS`)**: a 3px head with
  a 2-sample fading tail (comet mechanics, `in_out_cubic`) flies from
  (r=104, origin_deg) to the content core along the perpendicular-offset
  bezier (+24px control). The origin mark brightens to full luma at
  launch.
- **Condense — landing (100ms, `SIG_FOCUS_LAND_MS`)**: the focus ring
  collapses r 56→36 (`out_expo`) while content layers draw inside the
  gate; layer stagger 0/40/60/80ms preserved (`STAGGER_*_MS`); ghost
  slot Y-ramp trailing 60ms preserved (`SIG_IRIS_TRAIL_MS`).
- **Hold**: focus ring redraws each tick at r=92 (`SIG_FOCUS_RING_R`),
  1px arc, from −90°, sweep = confidence×360°, color = `conf_color`
  mapping. Static. Card-specific idles (spinner, waveform, drift pulse)
  unchanged.
  - Why r=92: outside every card's content extent (max ~r=88 for
    commitment links), inside the horizon band (100–108) — three
    distinct layers: content < ring < horizon.
- **Recede (160ms, `SIG_RECEDE_MS`)**: geometry contracts (exit-contract
  scale), text cuts at t=0.4 (kill-list #2 rule preserved), then a 3px
  head + tail flies core→(r=104, origin_deg); on arrival the mark pulses
  +1 luma tier for 300ms (`MER_ARRIVAL_PULSE_MS`) and settles at its
  ambient tier.
- **Crossfade**: `show_card(new)` during HOLD starts RECEDE(old) and,
  40ms later (`SIG_FOCUS_XFADE_LAG_MS`), CONDENSE(new). The receding
  card draws at ghost tier so exactly one solid motion exists per frame.
  No chromatic fringes; dynamic slots 3/4 are returned to the dream
  weather bank (see `CINEMA_V2_DELTAS.md §2`).
- Privacy-class cards (PrivacyVeil, Consent, ForgetLast, PrivateZone):
  slam entry preserved (rumble + shield unchanged), and they **never
  recede to a mark** — release is a hard cut. Privacy states must not
  leave residue.

## ASCII storyboard

```
t=0ms                t=90ms               t=140ms              t=240ms
   ' . |  *<--mark      ' . |                ' . |                ' . |
        \  brightens        *                 (  )  ring 56        KEYS
         \                    \                 *                (KITCHEN)
   .      \             .      *--.       .   content          .   ring
    seam                 seam   tail           gating           lands r36->
                                                                hold ring r92
                                                                sweep=conf

dismiss:  content cuts (t=0.4) -> head flies back -> mark pulses -> ambient
```

## reduce_motion

- Condense: content complete on first frame; landed focus ring drawn at
  full sweep=conf; an 8px static tick at origin_deg on the rim carries
  the temporal-origin reading (comet's v1 reduce variant, kept).
- Recede: hard cut; mark appears at final tier same frame.
- Hold ring: already static — identical in both variants (first
  signature where reduce_motion is a no-op; this is the standard the
  rest of v2 aims at).

## Failure modes

- **origin_deg missing**: condense from −90°. Honest: "this came from
  now."
- **origin outside dial window** (memory older than 5h): host clamps to
  the elder-tick angle (+58°) — arrivals from "earlier" all come from
  the same door.
- **Rapid-fire cards** (queue churn): the 40ms crossfade lag is fixed;
  if a third card arrives mid-crossfade the receding card completes as
  a hard cut (never two simultaneous recessions — bounded motion
  complexity per frame).
- **Data contradiction** (card re-shown while its mark is receding):
  the in-flight recession reverses from its current point — the head
  turns around; no teleport.

## Peripheral-glance test (400ms)

During travel: motion direction readable (something coming from the
right/past vs left/future) without reading content. During hold: ring
sweep readable as roughly full / half / sliver — the certainty
pre-reading v1's halo promised, minus the orbit that could read as
flicker (`HALO_CINEMA_V1_RISKS.md:78-88`).

## Daily-use test (day 30)

The law never varies, so it disappears as an event and persists as
grammar — exactly what should happen. What keeps carrying value on day
30 is the *differences* the constant law exposes: an answer that flies
in from 9 o'clock (this morning) vs one from the elder door; a sliver
ring on a shaky answer. Habituation to the motion is the mechanism that
makes the metadata legible.
