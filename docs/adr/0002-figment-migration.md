# ADR 0002 — Perception output: figments over bespoke cards, on an output-shape rule

**Status:** Accepted · **Date:** 2026-07 · **Scope:** on-glass output for perception/world lenses (Reality Compiler v2)

## Context

DreamLayer paints the glasses two different ways, and they do not share a
renderer:

1. **Cards** — `hud/cards.py` builds a typed dict (`type: "ScholarCard"`, a
   `layout`, some text), `bridge.send_card` ships it, and it is drawn by a
   **per-card-type twin**: a Python method in `hud/renderer.py`
   (`_spoken_caption`, `_scholar`, …) *and* a Lua entry in
   `display/renderer.lua`'s `DRAW[card.type]` dispatch. Today that is
   **~37 Python card renderers against ~46 Lua card draws**, each pair pinned
   by pixel goldens. A new card type is a new method in *both* languages plus a
   golden.

2. **Figments** — declarative scene-machine tables (`reality_compiler/v2/`)
   interpreted by a single, reviewed, whitelisted stage
   (`app/figment_stage.lua`, Python twin `interpreter.py`, JS twin
   `figment.js`). The stage draws only four primitives (text lines, counters,
   a pulse, bounded glyphs). Adding a *behavior* adds **no renderer code** — the
   figment is data, proven by `budgets.verify()` before it is signed, and the
   three interpreters are pinned by table-equality parity, not per-behavior
   goldens.

The two paths are mutually exclusive per frame (`main.lua`'s tick body is an
`if figment_active … elseif card …`), converging only at the Brilliant Labs
HAL. A card and a figment cannot co-own the screen.

We had drifted into building *perception* features — a live translation
subtitle, a "what am I looking at" label, an on-glass answer — as **bespoke
cards**, each paying the two-language twin + golden cost, even though what they
show is exactly what the figment grammar already draws: a line or two of
host-fed text with an eyebrow. This ADR settles when to reach for which.

## Decision

**A perception behavior's output shape decides its mechanism, on a three-way
rule:**

| If the behavior is… | …ship it as | why |
| --- | --- | --- |
| **a self-contained on-glass machine** that owns the screen for a while (a live feed, a timer, a countdown, a coached rep) — text + state + host-fed slots, no novel geometry | a **figment** | zero renderer twin; budget-proven; signed; auto-parity |
| **a transient overlay** with genuinely custom geometry that must appear *over* whatever holds focus (the privacy veil, a hark tap, a fact-check gauge) | a **card** | it needs a bespoke draw + must not seize the whole stage |
| **a host power a lens invokes**, not a screen at all (answer this, translate this, name this) | an **emit → capability** (ADR-adjacent: `capabilities.py`) | the *reaction* is host-side; the *screen* is whatever figment declared `requires` |

Concretely: **new world-facing text output is a figment by default.** A card is
now the exception, justified by custom geometry *and* overlay semantics, not the
default for "show some words."

The first migration under this rule — the **Rosetta Live pilot** — is done:
live voice translation moved from a per-utterance `SpokenCaptionCard` to
`native.rosetta_figment()` (named slots `langs` / `translation` / `original`,
`requires:[translate]`). The `SpokenCaptionCard` twin survives **only** for raw
transcript (`ops_conversation`); its translate use is retired.

## Rationale

1. **The parity-cost headline.** Every bespoke card is a *pair* of renderers
   (Python + Lua) plus a golden, kept in lockstep by hand. A figment is drawn by
   one already-reviewed stage; its correctness rides the table-equality parity
   the three interpreters already carry. Migrating a card to a figment does not
   move the cost around — it **deletes** the twin. (This is the claim the
   original writeup understated: the saving is not "less code here, more there,"
   it is a whole renderer pair and its golden retired. The Rosetta pilot proves
   it — no `_spoken_caption` change was needed for the translate path, and the
   lupa test draws the result through the *stage*, not a card twin.)

2. **All-or-nothing screen ownership is a feature, not a limitation.** Because a
   figment owns the screen while active, a translation lens is a *place you are*
   ("I'm in translate mode"), not a card that flashes and vanishes. That matches
   how these features are actually used — you turn on Rosetta and it stays — and
   it is why a *transient overlay* (veil, hark) correctly stays a card: it must
   appear over the thing that holds focus without taking it.

3. **The capability contract makes the third row safe.** A figment that shows a
   translation cannot *do* the translation — it emits nothing; the Brain fills a
   slot. The `requires:[…]` declaration (validated at author time, gated again
   at runtime in `rc_emit`, surfaced in the gallery) is what lets a data-only
   scene machine legitimately depend on a host power without becoming code. So
   "it's just data" stays true even for lenses that answer questions or name
   what you see.

4. **Grammar-minimality is the safety argument, so we keep the grammar minimal.**
   The stage is safe *because* it can only do four things. Every temptation to
   add a fifth primitive "so this one card can be a figment" is a temptation to
   widen the trusted base. The rule above resolves that tension the other way:
   if a behavior needs novel geometry, it stays a card (a bounded, reviewed,
   overlay twin) rather than growing the grammar. Named slots (WS-1) and the
   capability contract (WS-2) were the *only* additions the migration needed,
   and both are host-driven declarations with no new draw primitive and no new
   BLE-flood surface.

## Consequences

- **New perception text output defaults to a figment.** Reviewers should push
  back on a new `*Card` whose content is "an eyebrow + a line or two of text"
  and no custom geometry.
- **The card renderer twins shrink over time, never grow for text.** Candidates
  that fit the figment shape (e.g. `LiveCaptionCard`, `UpcomingCard`,
  `HereCard`, `MorningBriefCard`) can migrate incrementally; each migration
  retires a Python+Lua pair. Cards with real custom geometry or hard overlay
  semantics (`PrivacyVeilCard`, `HarkCard`, `TruthLensCard`/`FactCheckCard`
  gauges, `GlanceChoiceCard`) stay cards.
- **`SpokenCaptionCard` is now split by role.** Transcript keeps it; translation
  uses the figment. A future transcript migration is possible but out of scope
  for the pilot.
- **The three interpreters must stay in lockstep.** Any grammar the migration
  leans on (named slots) is pinned in Python, JS, and Lua by parity tests, as
  every grammar feature already is. This is the price of the whitelist, and it
  is cheaper than a per-behavior twin.

See `docs/rc_v2/figment_migration.md` for the practical how-to (the three
surfaces, `requires`, a worked Rosetta example, and the migration checklist).
