# Figment migration — the practical guide

Companion to **ADR 0002** (`docs/adr/0002-figment-migration.md`), which records
*why* perception output defaults to a figment. This file is *how*.

## The one question

> Does this behavior **own the screen** and show **text + state**, with any
> live content **fed by the host**?

- **Yes** → it's a **figment**. No renderer code. Skip to *Build the figment*.
- It's a transient overlay with **custom geometry over whatever holds focus**
  (a veil, a gauge, a shoulder-tap) → keep it a **card**.
- It's a **host power a lens calls** (answer / translate / name), not a screen →
  it's an **emit → capability**; the screen is the figment that declares
  `requires`.

## The three surfaces a figment has

1. **Text lines with tokens.** A line's `content` may use
   `{remaining}` `{elapsed}` `{count:<name>}` and the **slots**:
   - `{slot}` — the default host-fed line.
   - `{slot:<name>}` — a *named* channel (WS-1). One lens can hold several
     independent host-fed fields — e.g. a translation *and* its original.
     Names are inferred from the tokens (no schema field), bounded by
     `MAX_SLOTS = 8`, length-clamped to `MAX_TEXT_LEN`, and proven at author
     time. Filling a slot is a host-driven `text` event — no autonomous/emit
     cost, so the BLE-flood bound is unchanged.

2. **`requires: [...]` — the capability contract (WS-2).** If the lens depends
   on a host power — `ask` (the Brain answers), `translate`, `look` — declare it
   in `meta["requires"]` (helper: `capabilities.require(fig, "translate")`). The
   validator enforces **declared ⊇ emitted** and rejects unknown capabilities;
   the runtime (`rc_emit`) only fires a reaction the active lens declared; the
   gallery shows each power with a plain-words summary. A lens that is *fed*
   passively (a translation streamed into a slot, no emit) still declares what it
   consumes — that is the honest surface.

3. **Emits (optional).** A transition may carry a short `emit` tag. If the tag
   names a capability, it's gated by `requires`; otherwise it's a *free* local
   mark (`rep`, `round`, `beat`) the Vault can log.

## Build the figment

Figments are pure builders returning something `budgets.verify()` accepts. Put
built-in ones in `reality_compiler/v2/native.py`. The Rosetta pilot in full:

```python
def rosetta_figment(label: str = "Rosetta") -> Figment:
    fig = Figment(name=label[:24] or "Rosetta", initial="listen")
    fig.add_scene(Scene(
        id="listen",
        lines=[
            TextLine("{slot:langs}",       row=0, size="sm", color="accent_memory"),
            TextLine("{slot:translation}", row=1, size="md"),
            TextLine("{slot:original}",    row=3, size="sm", color="text_secondary"),
        ],
        on={"text": Transition(target=SELF),   # each utterance refreshes the slots
            "long": Transition(target=END)},   # a hold dismisses
    ))
    return require(fig, "translate")            # declares the host power it uses
```

## Feed it from the host

Deploy once (put + swap), then stream each update into a named slot. The
orchestrator does this over its bridge; the Brain does it via `rc_feed`. Both go
through `transport.text_envelope(figment_id, text, slot="<name>")`:

```python
if self._rosetta_figment_id is None or self._active_figment != self._rosetta_figment_id:
    fig = native.rosetta_figment()
    self.bridge.send_raw(transport.put_envelope(fig))
    self.bridge.send_raw(transport.swap_envelope(fig.id))
    self._rosetta_figment_id = self._active_figment = fig.id
for slot, val in (("langs", "ES → EN"), ("translation", tr), ("original", src)):
    self.bridge.send_raw(transport.text_envelope(self._rosetta_figment_id, val, slot=slot))
```

The named-slot text event flows to `figment_stage.lua`'s `on_event("text:<name>")`,
which is pinned in parity with `interpreter.py` and `figment.js`.

## Migration checklist

1. **Confirm the shape.** Text + host-fed state, owns the screen → figment. Novel
   geometry over focus → leave it a card.
2. **Write the builder.** Named slots for each host-fed field; `require(...)` for
   each host power; a `long → @end` escape (the wearer can always dismiss).
3. **Prove it.** `budgets.verify(fig).ok`. The slot/capability/paint caps all
   fire at author time.
4. **Wire the feed.** Deploy once, stream slots. Re-deploy if something else took
   the stage (`_active_figment != <id>`).
5. **Retire the twin.** Delete (or narrow) the card's use on this path. If the
   card type is now unused, its Python `_draw` and Lua `DRAW[...]` entry and its
   golden can go too — that's the win.
6. **Test end-to-end.** A lupa test that puts the figment on the real Lua stage,
   feeds the slots, and asserts the drawn text — parity is table-equality, not a
   per-behavior pixel golden.

## What has migrated / what stays

- **Migrated:** Rosetta Live (translate path) → `rosetta_figment`; the morning
  brief (wake path) → `morning_brief_figment` (named slots + a separator glyph,
  auto-clears after its window). Timers, intervals, clock were already figments.
  In both cases the live product path runs on the stage; the original card is
  kept only where a *second, non-product* consumer still needs it (the
  SpokenCaptionCard for transcript; the MorningBriefCard as a cinema-golden /
  demo showcase asset). Deleting a card's bespoke renderer pair outright is a
  follow-up gated on that showcase decision — see below.
- **Good next candidates** (text-shaped, screen-owning): `LiveCaptionCard`
  (already on the shared layout renderer, so migrating it retires a card *type*
  but no bespoke twin), `UpcomingCard`, `HereCard`.

### On actually deleting a renderer twin — the rule

**Migrate the live path; don't retire the card to chase a twin.** Moving a
feature's live glasses output onto the figment stage is the whole win, and it is
safe and reversible. *Deleting* a card's bespoke Python+Lua renderer is a
separate, much heavier step with a wide blast radius: a card type is usually a
first-class `ALL_SAMPLES` entry, so it feeds the marketing gallery export
(`hud/export.py`), the golden-image regression (`golden_images.py`), the demo
tour + feature catalog (`demo/`), the cinema-golden set
(`export_cinema_v2_golden.py` + a committed PNG), and sometimes a panel
marketing image. And the renderer is *bespoke for a reason* — multiline wrap,
adaptive sizing, stagger animation, or geometry the shared layout path doesn't
do — so removing it renders the card as a fallback, and collapsing it onto the
shared renderer degrades how it looks.

So: a renderer only deletes **for free** once its card type has genuinely no
remaining consumer (product *and* showcase). Renderer reduction is a
*consequence* of a card falling out of use — **never a goal worth degrading the
product or dropping a showcase card for.** When in doubt, migrate the path and
keep the card. If you ever do retire a card type outright, it must also: remove
it from `ALL_SAMPLES`, the golden sets (+ committed PNGs), and any demo/catalog
use — and that is a deliberate product decision, not a migration side-effect.
- **Stays a card** (custom geometry and/or overlay-over-focus): `PrivacyVeilCard`,
  `HarkCard`, the `TruthLensCard`/`FactCheckCard` gauges, `GlanceChoiceCard`,
  and `SpokenCaptionCard` in its remaining transcript role.
