# Cinema v2 — Migration (v1 → Meridian)

What changes for a user (and a developer) upgrading from Halo Cinema v1.

## What the wearer notices, day one

1. **The display is never black.** The resting state is the Horizon —
   your day as a ring of marks with a breathing notch at 12 o'clock —
   instead of the ReadyCard glyph or an empty screen. Nothing is
   required of you; it is a wristwatch, not a feed.
2. **Answers arrive differently.** Cards no longer materialize at
   center: they fly in from where the memory lives on the ring
   (yesterday's answer arrives from yesterday's direction) and, when
   dismissed, visibly return there. Dismissing no longer destroys — the
   mark stays.
3. **The confidence ring replaced the orbiting arc.** A still arc around
   the card, sweep = confidence. It does not move. Nearly-closed = sure;
   a sliver = shaky.
4. **Promises are visible before they're late.** Amber dots on the left
   (future) side, at their due hour. A promise starting to slip drifts
   off the ring inward and warms; a broken one goes cold and gray and
   ages into the past side. The alert card still fires exactly as
   before — the arc is under it, not instead of it.
5. **The Truth Lens looks completely different.** One thread around the
   verdict instead of nine rings: smooth green = consistent testimony,
   red tears = stages that deviated, gaps = insufficient evidence. Same
   analysis, same data, one glance.
6. **Dream mode no longer cuts away.** Double-tap changes the *light*,
   not the place: your day dims but stays, the weather flows around it,
   promises stay lit. Memory echoes now also light up the mark of the
   hour they came from.
7. **Privacy pause is visible at the rim too.** Paused = all marks gone
   + the notch turns gray. Resume brings the day back. Privacy-class
   prompts (consent, forget, private zone) now actually render on
   device — in v1 they queued and drew a black screen.
8. **The violet is gone.** High-confidence artifacts are now the
   brightest teal in the family instead of purple.

## Accessibility (reduce_motion)

Unchanged contract, stronger guarantee: every reading survives with the
motion off. Condensation appears complete with a static origin tick at
the memory's hour; the confidence ring is identical in both variants
(it never moved to begin with); the notch is a fixed tick; recessions
are hard cuts with the mark stepping in. Set via `settings.reduce_motion`
exactly as v1.

## For developers

### New surfaces
- `{t:"horizon"}` BLE message (`ble/message_types.lua` /
  `bridge/base.py RAW_FRAME_TYPES`) — composed day-ring, full-state,
  ≤48 marks, deci-degree angles. Composer:
  `orchestrator/horizon_composer.py`; device plotter:
  `display/horizon.lua`; phone mirror: `HorizonPreview.tsx`.
- `display/focus.lua` — the condensation/recession law; cards may carry
  `origin_deg` (the orchestrator stamps it on recall answers).
- Constant banks in `display/animations.lua`: `SIG_FOCUS_*`, `MER_*`,
  `TESTIMONY_*` — mirrored in `theme/motion.ts` (`signatures.focus`,
  `meridian`, `signatures.testimony`) and enforced by
  `test_cinema_v2_golden.py` parity tests.
- Raster harness: `bridge/lua_raster.py` + golden exporters
  (`hud/export_cinema_v2_golden.py`, `hud/export_cinema_v2_prototypes.py`).
  Goldens regenerate with
  `uv run python -m dreamlayer.hud.export_cinema_v2_golden`.

### Removed (all with in-PR replacements — defenses in CINEMA_V2_DELTAS.md)
- `transitions.iris_bloom`, `transitions.prism_slide`,
  `transitions.confidence_halo`, `transitions.memory_comet`,
  `transitions.comet_entry_angle` — callers migrate to `focus.*`.
- `SIG_IRIS_*`, `SIG_PRISM_*`, `SIG_HALO_*`, `SIG_COMET_*` constants.
- The `prism_cool`/`prism_warm` dynamic-slot aliases (slots 3/4 now
  belong to the dream weather alone; `themes.py DYNAMIC_SLOTS`
  updated).
- The device-side legacy 8-vector line-field fallback; no `line_field`
  frames now means no field.
- `PaletteShiftCard` removed from `ALL_SAMPLES` (it is a palette
  command, not a drawable card; its golden could only be a black disc).

### Behavior changes to be aware of
- `renderer.tick()` **draws every tick** (horizon idle) instead of
  returning when no card is active; `main.lua`'s Memory Mode branch now
  actually drives `Cards:tick` → `renderer.show_card/dismiss/tick` (the
  v1 branch was a stub comment).
- `DISMISS_MS` semantics: timers now time the release of focus
  (recession), not deletion. Values unchanged.
- Privacy-class cards (PrivacyPaused / Consent / ForgetLast /
  PrivateZone) hard-cut on release and never leave marks.
- `card_queue.lua` and `state_machine.lua` are **unchanged** —
  priorities, preemption, dwell and FSM transitions all carry over.
- While privacy-paused, bridges pass only the *empty* horizon frame
  (`pause_allows_raw`, both bridges).
- `ghost_wake_text` is now UTF-8 aware (multi-byte glyphs no longer
  slice; visible with the anchor renderer's bullets).
- `confidence_high` = `0xB8FFE9` in all three palettes — anything
  hardcoding the old violet is already wrong under the token rule.

### Test-suite migration
- `test_transitions.py` covers the Focus law + survivors (killed
  signature tests removed with their subjects).
- New: `test_horizon.py`, `test_horizon_composer.py`,
  `test_meridian_renderer.py`, `test_horizon_gate.py`,
  `test_cinema_v2_golden.py` (includes the anti-black-frame contract
  over every committed golden and the deterministic-regeneration
  pixel diff).
- Suites at this commit: host-python **657 passed**; root
  **159 passed, 1 skipped**.

## Rollback

Everything ships in one PR; reverting the merge commit restores v1
wholesale (goldens included, since they are committed artifacts). There
is no data migration: the ring buffer, memory DB, drift engine, and BLE
protocol layers are wire-compatible — v2 only *adds* the `horizon`
message type, which a v1 device build would drop as unknown, and v1's
`palette`/`line_field`/`sprite` frames are consumed unchanged by v2.
