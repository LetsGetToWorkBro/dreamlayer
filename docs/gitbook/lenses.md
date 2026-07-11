# The six lenses and the wider set

Everything DreamLayer does groups into six **lenses** — the product's mental
model, kept *in code* as a registry (`host-python/src/dreamlayer/lenses.py`,
with `all_features`, `find_feature`, and `lens_of` so the taxonomy is
queryable). Two things run underneath all of them: the **Privacy Veil** (the
spine) and **Atmosphere** (the ambient light: Inner Weather, the Prism Lens,
Palette Cycling).

| Lens | For | Features |
|---|---|---|
| **Memory** | your life, remembered | Dream Mode, Ghost Layer, Lucid Recall, REM, Yesterlight, Premonition, Waypath |
| **People** | who is around you | Social Lens, Timbre, Name Capture |
| **Truth** | what is true and where beliefs come from | Truth Lens, Candor, Provenance |
| **World** | understand what you look at | Juno (look-to-know), Label Lens, AI Brain, Rosetta, Puente |
| **Life** | do, keep, and build | Commitment Drift, Saga, Reality Compiler |
| **Together** | two wearers, one sky | Confluence |

The core lenses have their own chapters ([Juno](juno.md),
[Perception and memory](perception-memory.md), [Truth](truth.md),
[Saga](progression.md), [Privacy](privacy.md)). This chapter covers the rest
of the set — each fully wired into the orchestrator, each with a design spec
under `docs/`.

## Dream Mode and the night

**Dream Mode** (`dream_mode/`, spec `docs/DREAM_MODE.md`) is the double-tap
world: the display steps through a starfield door and becomes an instrument
rather than an assistant. While dreaming, camera and IMU frames feed the
engine (`on_scene_frame`), the microphone FFT feeds it (`on_audio_frame`),
and two card families render through the dedicated dream path on the device:

- **Ghost Layer** — world-anchored memory echoes. Stand where a memory
  lives and a pale **WorldAnchorCard** wakes, character by character.
- **Synesthesia** — a poetic six-word read of what the senses feel like,
  with a dominant color and a gestural sprite.

![Notes on the world — a memory pinned to a place](assets/demo/catalog/features/anchor/preview.webp)

**REM** (`rem/`, spec `docs/REM.md`) is the sleep cycle:
`maybe_dream_tonight(charging)` runs consolidation when the glasses charge at
night, gated by **NightWatch**. It dreams over the day's memories,
consolidates, produces a morning reel, and — the durable part — writes a
**RetrievalBias** the Horizon reads: what the night decided matters is
slightly brighter the next day.

**Yesterlight** (`docs/YESTERLIGHT.md`) folds yesterday's light back into
today's ring; **Premonition** (`docs/PREMONITION.md`) is the forward twin — a
`RecurrenceModel` sweeps for events that *usually* happen about now and
ghosts them onto the Horizon as breathing-dim dots (never brighter than the
real), hardening the model when a predicted event lands.

## Atmosphere

- **Inner Weather** (`docs/INNER_WEATHER.md`) — your own climate, made
  visible: dream-sky weather driven by your day's texture, rendered through
  the dynamic palette slots.

  ![Your inner weather](assets/demo/catalog/features/inner/preview.webp)

  | A quiet dream sky (device Lua) | An anchor echo in weather (device Lua) |
  |---|---|
  | ![Storm](assets/device/weather_dream_storm.webp) | ![Echo](assets/device/weather_anchor_echo.webp) |

- **Prism Lens** (`docs/PRISM_LENS.md`) — the kaleidoscope, rebuilt in Lumen
  with spring bloom, breathing rotation, and counter-rotating halo rings,
  inside strict photosensitivity caps.
- **Palette Cycle** (`docs/PALETTE_CYCLE.md`) — slow ambient color flows
  through the leased slots (`display/palette_cycle.lua`).

## World — look at anything

- **Scholar** (`orchestrator/scholar.py`) — read the question and answer
  it, spell out a form's fields, or put dense text in plain words; and
  **TasteLens** (`orchestrator/taste.py`) — the shelf/menu choice engine
  with hard dietary vetoes and plugin data connectors. Both routed by the
  Glance Arbiter or voice; full chapter:
  [Scholar and TasteLens](world-lenses.md).
- **Object Lens / Juno-look** (`object_lens/`, specs `docs/OBJECT_LENS.md`)
  — `look_at_object(frame, facet=None|"own"|"ai"|"shop")` builds a
  contextual panel for the thing in view. Providers plug in per domain
  (an AI provider backed by the tiered brain, a label provider, Rosetta for
  text); integration seams exist for a laptop, a car, a plant. The lens never
  identifies people — `PERSON_LABELS` enforcement keeps humans in the Social
  Lens's consented domain.
- **Rosetta** (`rosetta.py`) is the **eye**: text you look at — a menu, a
  sign — OCR'd and translated (`translate_seen(text, target)`). **Puente**
  (`orchestrator/puente_bridge.py`) is the **ear**: real-time speech
  translation into LiveCaptionCards. Complementary by design; they share
  card styling, not pipelines. **Seams:** OCR, the translation model, and
  the microphone.
- **Waypath** (`find_way(subject, heading_deg)`) — point-me-to-my-things:
  a bearing card from your heading to where the remembered object lives.
- **Docent** (`docent(query)`) — a venue's own knowledge, answered on its
  premises from its published collection, offline; and **Rosetta Live**
  (`translate_heard`) — live speech translated to caption cards, offline
  with the Argos pack. Both in
  [the World lenses chapter](world-lenses.md#docent--the-venue-speaks).
- **Thread** (`thread(image)`) — steal color from the world: the palette
  of whatever you look at, quantized to six named swatches and kept as a
  recallable memory. The image itself is never stored — only the swatches.
- **Retrace** (`retrace(subject)`) — "where did I last *see* it": recall
  from passive sightings, blended by confidence and recency
  ([Perception and memory](perception-memory.md#ask-and-receive--object-and-commitment-recall)).
- **Ember** (`ember()`) — the gentle anniversary layer, sensitive by
  design: at most **one** memory, only one you *chose to keep* (pinned),
  from about a year ago today — and it stays silent entirely when your
  inner weather reads storm.

## Truth's siblings

- **Candor** (`check_consistency(claim)`, spec `docs/COMMITMENT_DRIFT.md`
  neighborhood) — the on-device self-consistency check: does this claim
  contradict what *you* have said and kept? Emits a ConsistencyCard; never
  touches the network. Veritas reuses its `contradicts` predicate for the
  speaker-against-themselves pass.
- **Provenance Lens** (`trace_provenance(claim)`, `docs/PROVENANCE_LENS.md`)
  — where did this belief come from? Traces a claim to its origins and
  standing in your own record; pairs with the `Answer.sources` attribution
  that every brain answer carries.
- **Candor Mirror** (`orchestrator/candor.py`) — the truth machinery,
  pointed inward. It listens only to *your own* lines: live speaking pace
  (a gentle nudge when you sustain past 165 wpm), a filler-word tally
  (hidden until you peek), and your own narrative drift folded in from the
  consistency check. The debrief card — eyebrow "How you spoke" — reads
  like: *"162 wpm (up), 9 'um's, and you told the project story
  differently than Tuesday."* Inward-only by construction, and the Veil
  silences it completely. The design point is written into the module: a
  deception pipeline pointed at others is a scandal; pointed at yourself
  it is a coach — and only an open codebase can prove which one it is.

## Life — building and keeping

- **Commitment Drift** (`docs/COMMITMENT_DRIFT.md`) — promises as physics:
  states run blooming, healthy, drifting, cracking, shattered;
  `nudge_commitment` / `keep_commitment` / `break_commitment` move them;
  `tick_drift` raises the drift card as decay grows. The Horizon draws the
  arc; a broken promise shatters exactly once.

  ![Before it slips](assets/demo/catalog/features/drift/preview.webp)

- **Reality Compiler v2** (`reality_compiler/`, specs `docs/rc_v2/`) — the
  build-a-skill path: **Rehearsal** compiles a described procedure
  ("three rounds of two minutes, bell between") into a signed **Figment** —
  a budget-verified little program that runs *on the glass stage* with the
  button driving it. `build_skill(name, text)` is the orchestrator surface;
  the wire protocol has first-class figment put/swap/revoke/ack messages,
  and the phone's Rehearsal screen is now **live end to end** — every beat
  round-trips the Brain's `rc/*` endpoints (rehearse, keep, deploy, revoke),
  with deploys recording BLE envelopes until the glasses transport attaches.
  Juno also compiles **native timers, intervals, and a clock** through
  the same engine, on the spot, with or without a Brain
  ([Juno](juno.md#3-timers-intervals-and-the-clock--no-brain-required)).
  The five recorded sessions under `out/rc_v2/` (round timer, rolling
  rounds, spar night, a refused strobe — the safety path — and hot-swap
  revoke) are its executable spec, alongside `docs/rc_v2/echo.md`,
  `loom.md`, and `rehearsal.md`.

  The compiler now also **teaches itself**, three ways: **repertoire
  ranking** learns which kept figment you start where and when, and offers
  exactly one — "Gym timer — start the usual?"; **rehearsal refinement**
  notices the scene you keep banishing a figment at ("You end Rounds
  around 20:00 of 25:00 — every time.") and proposes a trimmed variant,
  which re-runs the whole budget-verify-and-sign path before it can
  deploy; and **grammar mining** counts the phrasings the parser keeps
  failing on, locally, so the closed grammar grows from real misses rather
  than guesses. The grammar itself grew too: **cadence scenes** (a slow
  breathing envelope in seconds — never a flicker), **place and presence
  events** (`place:enter`, a bonded partner's emit as your transition),
  IMU gestures, and **ledger emits** — a figment's taps recorded into a
  performance log you keep. And a kept figment can now carry a
  **dedication**: signed into its canonical bytes, an heirloom another
  device can inherit and prove came from you.

## Together — Confluence

**Confluence** (`confluence/`, spec `docs/CONFLUENCE.md`) is two wearers, one
sky: a consented **bond** entangles two Horizons; togetherness drifts and
settles as you move through the day apart or together. **TinCan** sends a
single tap down the wire as a gentle ping; **weather gifts** let one wearer
send the other a sky. The orchestrator surface is
`attach_confluence(bonds, sky)` / `receive_confluence(wire)` /
`outgoing_weather()`, with a tap collector feeding single-clicks while
dreaming. **Timbre** (`docs/TIMBRE.md`, People lens) gives known voices their
own audio texture. The phone's Confluence screen presents the bond
lifecycle; live two-device streaming is the pre-hardware seam.

The bond now scales to a group: **GhostMode mesh** entangles a whole circle
under one three-word code, and **The Beacon** finds your people in a crowd
by feel — bearings and distance bands, never coordinates. See
[The platform](platform.md#pillar-2--ghostmode-mesh-and-the-beacon).

## Lucid Recall — the query router

`lucid_recall/router.py` is the ask-and-receive front door: it classifies a
query (face keywords route to the Social Lens; fact keywords to the memory
index and the tiered brain) and returns one HUD card. The AI knowledge tier
folds into it — "ask about your own stuff" *is* Lucid Recall extended from
memory to your files and mail.
