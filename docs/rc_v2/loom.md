# Loom — Deep Dive (Phase 3 survivor)

> Behaviors are strands — a time strand, an event strand, a display strand —
> and you braid them on the phone with your thumbs.

## 1. Full paradigm description

Loom accepts the phone/HUD split as a feature: structure is shaped on the
phone, felt in the eye. The phone shows a vertical **loom**: time flows top to
bottom, strands hang from **anchors** (event sources) and pass through
**knots** (bounded operations). The braid *is* the program:

- **Anchors** (strand sources): `double-tap`, `single-tap`, `hold`,
  `every second`, `battery`, `coach byte`, `on arm`.
- **Knots** (operations a strand can pass through): `count down <t>`,
  `count up`, `count taps`, `show <layout>`, `pulse <color> <window>`,
  `send to phone`, `wait <t>`, `end`.
- **Crossings**: pulling one strand across another merges control — a tap
  strand crossing a countdown strand becomes start/stop; a coach-byte strand
  crossing a display strand becomes interrupt-and-resume.
- **Loop cuff**: clipping a strand's end back onto one of its own earlier
  knots makes a cycle — the cuff physically *won't clip* onto a point that
  would make a zero-time loop (the knot glows red and the phone gives a
  refusal haptic).

A live **Halo mirror** at the top of the screen runs the braid continuously
as it is tied; deploy is flicking the braid upward.

## 2. The complete surface

One phone screen, three regions:

```
┌────────────────────────────────┐
│  ◉ Halo mirror (live)          │   ← braid runs here as you tie it
├────────────────────────────────┤
│  anchors: [2-tap][1-tap][sec]  │
│           [battery][coach][arm]│
│                                │
│   2-tap ─┐                     │
│          ├─● count down 3:00   │
│          │      │              │
│          │      ●─ show BIG    │
│          │      │              │
│          │      ●─ pulse ▓ 10s │
│          │      ╰──cuff──╮     │
│          ╰───────────────╯     │
│                                │
│  knots:  [count][show][pulse]  │
│          [send][wait][end]     │
├────────────────────────────────┤
│        ⤒ flick to deploy       │
└────────────────────────────────┘
```

No gesture set on-glasses (Loom authors entirely on the phone); no voice
grammar. The knot palette is the complete vocabulary — there is nothing else
to learn and nothing else expressible.

## 3. Safety model

Identical substrate to Rehearsal — braids flatten to Figments and pass the
same static verifier — but Loom adds **refusal at authoring time**: an
illegal braid is physically untieable. Knots that would exceed a budget
refuse to snap; the loop cuff refuses zero-time cycles; the `send to phone`
knot won't accept placement inside a sub-second loop. The verifier still runs
before signing (defense in depth), but in Loom it should never fire — the
editor's affordances are the theorem, the verifier is the proof-check.

## 4. Teachability model

Failure is *pre-emptive and physical*: the red-glow + refusal haptic happens
at the exact knot, before the mistake exists. For the residual cases (a braid
that verifies but behaves surprisingly), the mirror is the teacher — it runs
the braid live, so surprise arrives during authoring, not after deploy.
Tapping any knot shows a one-line plain-words reading of that knot ("when the
countdown hits 0:10, breathe coral twice a second").

## 5. Runtime model

Same as Rehearsal from the Figment down: braid → Figment → verify → sign →
vault → `figment_put`/`figment_swap` over BLE → fixed `figment_stage.lua`
interpreter with dynamic clamps. The only Loom-specific host code is the
braid editor and the braid→Figment flattener; the mirror reuses the host-side
Figment interpreter at 1× (not folded) speed.

## 6. Backward-compat story

Every v1 intent lifts to a Figment (shared `compat.lift`), and every lifted
Figment **renders as a braid** — the braid view is derivable from the Figment
graph (anchors = trigger events, knots = scenes/ops). v1's 15 templates
therefore appear in Loom as 15 pre-tied braids the user can study and re-tie,
which doubles as the paradigm's tutorial.

## 7. End-to-end trace: "3-minute rolls timer, 10-second pulse"

1. User opens Loom, drags the `2-tap` anchor onto the loom — a strand drops.
2. Pulls it through `count down`, dials 3:00 on the knot's wheel.
3. Pulls through `show BIG` (mirror immediately shows `3:00` counting).
4. Pulls through `pulse`, picks coral, dials window 10 s (mirror shows the
   breathe when it scrubs near the end).
5. Clips the loop cuff back onto the anchor (legal: the cycle consumes
   180 s).
6. Flicks upward: verify → sign → deploy; the mirror header flips to
   `ON HALO`. Double-tap at the gym starts round one.

~45 seconds, two thumbs, zero syntax.

## 8. The one test that proves the paradigm

**The untieable-mistake test.** Enumerate every budget-violating braid one
knot-placement away from a legal braid (display-rate, BLE-rate, zero-time
cuff) and assert the editor refuses each placement *and* that force-flattening
the refused braid fails the static verifier with the same violation. If any
unsafe braid is tieable, or any refused braid would actually have verified,
the affordances and the theorem have diverged and the paradigm's core claim —
"illegal programs are untieable" — is false.
