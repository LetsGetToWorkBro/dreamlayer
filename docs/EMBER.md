# Ember — memories you tend until they live in you

> Every other company wants to remember your life for you.
> Ember would rather you remember it yourself — and then it burns the tape.

Every Memory-lens feature stores your life *for* you. Ember runs the other
direction: it strengthens your **biological** memory with retrieval practice
(the testing effect) at expanding intervals (the spacing effect), gated to the
places where the moments happened (the method of loci, made literal), and —
this is the heresy — **offers to delete the recording once you truly know
it.** Not a memory prosthetic. A memory gymnasium. The archive that empties
itself into you.

The loop, as the wearer lives it:

1. **Tend** (phone, over coffee) — after the glasses dream (REM), the morning
   offers up to nine of yesterday's moments. You keep at most three. Nothing
   is kept without your explicit choice.
2. **Reach** (glasses, in the world) — days later, at the doorway where it
   happened, a hearth-gold glow asks four words: *"What did Dad say about the
   ice?"* Never the answer. You speak your recall; it's graded gently and the
   curve advances. Walking past costs nothing.
3. **Burn** (phone, with consent) — when stability crosses ~90 days the
   memory lives in you, and the recording becomes a standing offer. One
   explicit confirmation and the raw trace is purged — row *and* ANN vector —
   leaving a cue-only tombstone the anniversary Ember card can resurface a
   year later, for you to answer from the only place it still exists.

## Architecture

```
                     night, on the charger
  SemanticRingBuffer ──▶ REM cycle ──▶ TendingPass ──▶ tending offers
        (the day)         (dreams        (ember/           │ phone ritual
                           boost the      tending.py)      ▼ keep ≤ 3/day
                           ranking)                   EmberStore (<db>.ember)
                                                            │
  place signature ──▶ on_place ──▶ tick_ember ──▶ EmberPromptCard (cue only)
   (ops_commitments)   (ops_ember.py)   │
                                        ▼ wearer speaks (no wake word)
                       handle_voice ──▶ ember_attempt ──▶ grading.py
                                        │                  │
                              FSRS-shaped scheduler ◀──────┘
                              (ember/scheduler.py)
                                        │ stability ≥ 90d
                                        ▼
                       EmberGraduatedCard ──▶ phone ceremony ──▶ burn
                                             (consent=True only) (ceremony.py)
```

Everything runs on the phone hub by default — the scheduler, the store, the
grading are pure Python with zero dependencies. A connected Mac Brain
upgrades grading with semantic similarity through the embedder ladder; the
lexical grade is the offline floor, and the semantic hook can only ever grade
*more* gently.

## Quick start

```python
from dreamlayer.main import build

orc = build()

# the phone's ritual, compressed: keep a moment as an engram
e = orc.embers.keep(
    "k1", "What did Maya say?",                  # the cue — never the answer
    "Maya said her first full sentence in Spanish",
    kept_at, place_signature="sig-kitchen")

# days later, standing in the kitchen:
orc.on_place("sig-kitchen")                      # → EmberPromptCard (cue only)
orc.handle_voice("she said her first sentence in spanish")
#                                                → EmberFlareCard, curve advances

# months later, after graduation:
orc.burn_ember(e.id, consent=True)               # purge + cue-only tombstone
```

CLI readout (read-only by design — burns stay on live-Brain surfaces):

```
$ dreamlayer ember status
→ tending 3  ·  due 1  ·  graduated 1  ·  burned 2  ·  offers waiting 0
$ dreamlayer ember log
  ★ 'What did Maya say?'  S=101.2d reps=7 lapses=0  due in 44.0d
  🔥 'What did Dad say about the ice?'  — burned; lives in you
```

## Card types

| Card | Priority | Dismiss | Description |
|---|---|---|---|
| `EmberPromptCard` | AMBIENT | 12 s | The glow: cue + place, **never the answer**. Unanswered = MISSED, never a lapse. |
| `EmberFlareCard` | AMBIENT | 2.6 s | You reached and it was there. One breath, gone. |
| `EmberRevealCard` | CONTEXT | 9 s | You reached and it wasn't. The answer, gently — the *only* surface that renders it. |
| `EmberGraduatedCard` | CONTEXT | 9 s | Stability crossed the line. Announces the offer; the burn is phone-side only. |

All four share one visual grammar in `halo-lua/display/renderer.lua`: a
breathing hearth-gold ember (`palette.ember_glow`, deliberately outside both
the alarm family and the memory teal).

## The scheduler (ember/scheduler.py)

FSRS-shaped: memory state is a `(stability, difficulty)` pair; retrievability
decays along `R(t) = (1 + t/9S)^-1`; prompts fire when R is projected to hit
0.90. Pure functions of `(state, outcome, now)` — no clock reads, no
randomness, no I/O — so `dreamlayer ember log` is a trustworthy readout.

The grades, and the two that carry the product's values:

- `MISSED` — the prompt fired and you walked on. **Not a lapse.** Nothing was
  tested, so nothing is penalised; the engram just comes due again.
- `FORGOT` — you reached and it wasn't there. Stability drops, and the
  rebuilt trace regrows ~15% faster (the savings effect).
- Graduation (stability ≥ 90 days, typically five to ten recalls across half
  a year or more) is a **ratchet**: a later lapse shrinks the curve but never
  revokes the earned offer. Deletion is earned slowly, on purpose.

## The Privacy Veil contract

- **Prompting is recall** — behind `allow_recall()`: the full pause veil
  silences every glow; incognito does not silence what you already own.
- **Tending is capture-adjacent** — the nightly staging runs behind
  `allow_capture()`: a veiled evening stages nothing, and moments marked
  `private` / `no_dream` are never offered (same door policy as REM).
- **The answer never leaves the hub.** `GET /dreamlayer/ember` ships cue +
  curve only; the phone cannot leak what it never holds. `dreamlayer ember
  log --answers` is veil-gated like `memories browse`.
- **The burn is honest.** It goes through `Retriever.purge_memory` — the row
  and its ANN vector together (a burn that leaves the moment recallable by
  similarity would be a lie) — and requires literal `consent=True` at every
  layer: ceremony, endpoint, and phone store all refuse anything truthy-but-
  not-true.
- **Engrams outlive memory lifecycle events by construction**: the store is
  its own SQLite file (`<db>.ember`), invisible to `RetentionSweep` and
  `purge_all` — an engram is a record of what *you* know, not what the
  glasses know.

## What Ember refuses to be

No scores, no streaks, no shame. A missed recall reschedules silently. The
tending ritual caps at three keeps per day on every surface — a ritual, not
an inbox. And nothing is ever burned automatically: graduation creates an
offer, never an act.

## Testing

```
host-python:  pytest src/dreamlayer/tests/test_ember_scheduler.py \
                     test_ember_store.py test_ember_tending.py \
                     test_ember_ops.py test_ember_render.py \
                     test_ember_endpoint.py
halo-lua:     luacheck .          (renderer budget: test_ember_render.py
                                   drives the real device Lua)
phone-app:    npm test -- ember-store
```

The invariants the suites pin: the cue never contains the answer (payload,
device constructor, and endpoint all checked); prompts never stack; an
expired prompt never swallows ordinary speech; the wake word always bypasses
the glow; graduation is a ratchet; burns require literal consent and leave
only the cue.
