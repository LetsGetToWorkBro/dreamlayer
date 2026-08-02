---
id: 0007
title: Each of the 21 dormant capabilities, and what is actually blocking it
status: confirmed-deferred
date: 2026-08-01
area: capabilities
---

## Claim

`HANDOFF.md` says of the dormant list: *"Each is a decision — wire it Brain-side,
or move it to `_BY_DESIGN` with a reason."* The claim under test is the implicit
one behind that sentence — **that each of these is one wire away**, and the list
is shrinking because nobody has got to them.

Stated in its strongest form: *these are built, tested adapters; connecting them
is an afternoon each, and the count going down is a matter of effort.*

## Verdict

For 4 of the 21 that is roughly true and the work is real — all four are now
built, and each took a feature rather than a wire (see the updates). For the
other 17 the
blocker is not effort — it is a missing producer, a missing consumer, a
dependency whose weight or whose downstream feature is the real question, or a
claimed interface the seam does not fit.
Wiring most of them means BUILDING THE OTHER HALF, which is a feature decision,
not a connection.

Counted the same way each time: 63 library capabilities on this machine, of
which **39 are wired to a live path**, **3 run on the glasses hub**, and **21 are
dormant**. This entry is about the 21.

## Evidence

Dependency availability is from `importlib.util.find_spec` in the dev container;
caller analysis parses each seam's public names (including those defined under
`if _HAS_X:`, which is how every optional seam here is written) and greps the
tree for a construction outside the seam and outside `tests/`.

### A — blocked on a producer or consumer that does not exist (4)

| capability | what is missing |
|---|---|
| `event_bus` | ~~`MeshManager` is constructed nowhere in the tree.~~ **Built — see the update below.** |
| `object_tracking` | ~~Nothing emits per-frame centroids.~~ **Built — see the update below.** |
| `wasm_plugins` | ~~Needs a `.wasm`-guest package format.~~ **Built — see the update below.** |
| `extism_plugins` | ~~The same missing format, a second runtime.~~ **Built — see the update below.** |

### B — Orchestrator or simulator by design (5)

`fs_watch`, `lan_discovery`, `spatial_viz`, `structured_concurrency`,
`frame_glasses`. Their seams live under `orchestrator/`, `simulator/` or
`bridge/`, which `scripts/capability_reachability.py` already treats as
by-design-unreachable from the Brain (decisions/0001). Reaching them from the
Brain would be the regression.

### C — ~~dependency will not install in this environment~~ (5)

**This heading was wrong and the correction is below (2026-08-02).** All five
resolve. What is true is that four of them arrive with a CUDA/torch stack and
the fifth with an agent framework, and that each is downstream of a decision
that is not about the dependency at all.

`asr_alignment` (whisperx), `diarization` (diart), `facial_aus`
(libreface/pyfeat/facetorch), `persona_tuning` (human-learn), `typed_pipeline`
(pydantic_ai).

### D — the interesting ones: dependency present, and still not one wire (7)

* **`skia_render`** — its docstring claimed it *"exposes it behind the SAME
  `fn(card)->PIL.Image` shape `CardRenderer.register(card_type, fn)` already
  accepts"*. It does not. `register`'s callback is `fn(draw, card)`, and
  following the old instructions raises on the first card:

  ```
  TypeError: _render() takes 1 positional argument but 2 were given
  ```

  Worse, `_skia_blank` clears to black and writes `card["title"]`, a key HUD
  cards do not carry — so even with the arity fixed it would replace every
  working card with a black square, under the floor an optional dependency owes.
  Corrected in place; see `tests/test_skia_seam_claims.py`.

* **`structured_output`** — see the 2026-08-01 update below: settled, and the
  thing it was for is built without either library.

* **`plugin_entrypoints`** — the safe API now exists (discovery no longer
  imports; loading takes an explicit policy). What it lacks is a policy worth
  writing: an entry point advertises a module path, not a signed package, so
  there is nothing for `PluginStore`'s publisher/first-party machinery to check.
  The only honest policies are an explicit wearer-maintained allow-list or
  refusal, and no third-party DreamLayer plugin ships as a pip package yet.

* **`typed_docs`** — `MemoryDoc` has no consumer. `MemoryDB.add_memory` takes
  fields, not a document; an `add_doc()` adapter is easy and nothing would call
  it.

* **`asgi_server`** — an adapter for a dispatch function the caller supplies.
  There is no such dispatch in the tree, which is now what the module says.

* **`lsl_streams`** — a research export with no product consumer.

* **`wake_word`** — no wake engine exists to drive it.

## What would overturn this

Per group, and each is cheap:

```
A: grep -rn "MeshManager(" host-python/src --include=*.py | grep -v tests
   → answered: ai_brain/server/live_circle.py constructs one per member
C: pip install --dry-run whisperx   (etc.)
   → answered: all five resolve; see the 2026-08-02 correction
D: grep -n "def register" -A 3 host-python/src/dreamlayer/hud/renderer.py
   → a one-argument callback would make skia_render's original claim true
```

For the whole entry: `python -m dreamlayer.capabilities` and the counts in
`capability_reachability.py`. If wired rises above 39 without this file
changing, the file is stale.

## Update — 2026-08-01, `wasm_plugins` (group A, row 3)

Built, and the entry's own framing held: it was a FEATURE to design, not a wire.
What it took was three separate blockers, and the first two would each have made
the third worthless on its own — which is exactly the failure mode this file is
about.

1. **No package format.** `manifest.kind` now selects `"python"` or `"wasm"`;
   the payload lands as `<module>.wasm` and rides in `source` as base64 so the
   checksum and signature rules are untouched. `kind` is INSIDE
   `signing_payload()`, because flipping it chooses which host runs the code —
   the same as choosing the sandbox.
2. **The gate refused every wasm package.** Base64 is not Python, so
   `scan_source` answered `syntax error: cannot assign to expression` for all of
   them. Routing them in `store.py` was necessary and not sufficient: they could
   never reach the loader. `plugins/wasm_scan.py` reads the module's import and
   export sections directly — no runtime, because the gate runs at install time
   on machines that have none — and `validate.scan_wasm` refuses a guest reaching
   past its manifest, naming the capability the author would have to declare.
3. **The host could not pass a guest a string.** `log`, which the WIT calls "the
   minimum a plugin needs to speak to the host at all", received two integers
   and had no way to read the bytes they pointed at. `read_mem`/`write_mem` are
   bounds-checked against the guest's live memory size and refuse rather than
   clamp.

Two bugs fell out that were not in this entry's ledger at all, both only
reachable once a guest actually ran: `_wrap` returned `0` from every host
function, so granting a VOID capability (`log`, `cards`) trapped the guest with
"callback produced results when it shouldn't"; and `granted` was handed raw
manifest names, so `network` never linked `net` and `log` linked for no one.

The capability is now in `_PROMOTED_AT_RUNTIME`, not removed from `_NOT_WIRED`:
wasmtime importing is not a guest. `DL_WIRED_WASM_PLUGINS` follows
`wasm_plugin_host.live_guests() > 0` — a `.wasm` package instantiated right now
— so removing the plugin takes the capability back down.

`extism_plugins` (row 4) was blocked on "the same missing format", and with the
format built the rest was one `kind`. `manifest.kind == "extism"` ships the same
`.wasm` on disk under the Extism runtime, which links NO host functions at all —
incapable rather than inspected. `extism_host.py` had been complete, tested and
bounded for months with exactly one caller: its own tests. It was never missing
a runtime; nothing on disk was ever an Extism guest.

Three things had to differ from its sibling and none of them were guessed:

* The gate reads a different namespace. An Extism guest imports
  `extism:host/env` (the PDK's `alloc`/`store_u8`/`output_set`), which under the
  component host's rules reads as "outside the host surface" — so `scan_wasm`
  takes the runtime's namespace as a parameter. It is the STRICTER check of the
  two: there is no capability to declare, because there is no power to grant.
* No `memory` or `dl_alloc` export to insist on; the PDK owns both sides.
* The smoke test is a real call, because Extism constructs its plugin per call
  and has no instantiate step. An EMPTY reply is not a failure — `{}` is not a
  sighting, and "nothing to say about this one" is the answer a good provider
  gives most of the time.

Both capabilities are promoted from their own live count (`live_guests()` per
runtime), never each other's: a wearer running one is not running the other.

## Update — 2026-08-01, `object_tracking` and `event_bus` (group A, rows 1–2)

Both were "a missing producer", both were features to design, and in both cases
the half that existed was the one nobody could reach.

**`object_tracking`.** `SupervisionTracker.update([(cx, cy), …])` has taken a
centroid list since it was written and nothing in the tree ever produced one —
`YoloClassifier.__call__` throws the geometry away because the Object Lens wants
one subject. `detect()` now returns every box with a normalised centroid, and
`detections()` fans the whole ladder onto one shape: a localising rung gives
positions, every other rung gives one label with `centroid=None` rather than a
fabricated centre point, which would have made every label-only rung report an
object that never moves at the same spot forever.

The consumer is `orchestrator/object_trail.py`, and the design question it
answers is the one this entry warned about — the obvious feature (detect a thing
being SET DOWN) cannot be built honestly, because only one rung can localise
anything, so motion-that-stops would be silently dead on most Brains.
DEPARTURE needs no geometry, works on every rung, and gets better with a
localiser instead of requiring one. It feeds `WaypathLens`, whose own docstring
had always claimed anchors were dropped "when it sees where you left something"
while every anchor in fact came from the wearer narrating one aloud.

**`event_bus`.** `MeshEventBus` wraps a `MeshManager`, and
`Orchestrator._init_confluence_plugins` sets `self.mesh = None` with the comment
"attached by the app layer when a circle is formed". No app layer ever formed
one, so GhostMode — a headline of the product, with a normative protocol
document — was unreachable from every surface a wearer has.
`ai_brain/server/live_circle.py` is the room, built as the exact sibling of
`live_confluence.py`: the Brain as the pre-hardware meeting point, over the real
primitives, adding no crypto and no receive rule of its own.

One defect fell out that only a live subscriber could reach: `_MiniEmitter` (the
dependency-free fallback) catches a raising listener and pyee's `EventEmitter`
does not, so with the optional dependency INSTALLED one bad subscriber broke a
mesh beat that had already been signed and sent. That is the floor principle
inverted — an optional dependency doing less than the fallback it replaces — and
the guard now lives in `MeshEventBus`, where it covers both paths.

Both are promoted from proof, never from a wheel being importable: a real
ByteTrack that has actually been handed a centroid, and a circle live on this
Brain right now.

## Update — 2026-08-01, `structured_output` (group D): settled, still dormant

Judgement asked for and given. **Neither library gets wired, and the thing they
were wanted for is now built without them.**

Why not, concretely:

* `outlines` constrains a sampler **in this process**. The model on this path is
  `backend.chat(prompt) -> str`, an HTTP POST to Ollama. There is no sampler
  here to constrain.
* `instructor` patches an OpenAI-compatible **client object**. There is none;
  creating one means adding an HTTP client dependency to reach a server the
  Brain already talks to directly.
* Worse than either: both return a *validated structured object*, which on this
  path means the model CHOOSING the behaviour. `intent_parser_llm`'s whole
  design principle is that "the model only suggests; the deterministic matcher
  decides". Handing it a typed `BehaviorIntent` inverts that, on the one path
  the reality compiler's safety story rests on.

What the capability was actually for — a restatement that cannot land outside
the closed grammar — is now delivered by the **model server's own** schema
field: `_gen` passes a JSON Schema whose `behaviour` is an enum of the fifteen
phrasings `IntentParser` reads, so the sampler cannot emit a sixteenth. The
deterministic matcher still decides, no dependency was added, and a server that
ignores `format` is simply asked again unconstrained — the floor an optional
path owes.

Two consequences recorded in code, not only here:

* The seam no longer *imports* `instructor`/`outlines`. Both were probes behind
  a gate that had already been removed as wrong (they gated a path neither
  library takes part in), and a module holding a second copy of the capability
  catalogue's dependency claim is a second thing that can be wrong — it already
  was.
* The catalogue's `gain` string used to promise these libraries "constrain the
  model AT GENERATION so a malformed suggestion can't be produced in the first
  place". That is now true and free, so the sentence described a benefit the
  install cannot add. Rewritten to say so, ending "installing them adds nothing
  here", with `tests/test_capability_gain_honesty.py` pinning it.

The capability stays in `_NOT_WIRED` — not moved to `_BY_DESIGN`, because the
rule that bucket encodes is about the Brain/Orchestrator split and does not
apply. It reports `dormant`, `wires_on_install` is False, and the wearer's
install hint reads "installs the library; nothing calls it yet", which is
exactly the truth.

## Correction — 2026-08-02, group C: they all install

The heading claimed the dependency "will not install in this environment". That
was asserted from `importlib.util.find_spec` returning None — which says the
library is not installed HERE, and says nothing whatever about whether it could
be. Measured properly with `pip install --dry-run`, **all five resolve**:

| capability | dependency | resolves | what comes with it |
|---|---|---|---|
| `persona_tuning` | `human-learn` | yes, seconds | 5 packages (bokeh, clumper, shapely, tornado) |
| `typed_pipeline` | `pydantic_ai` | yes | ~60: anthropic, google-genai, mcp, logfire, opentelemetry, keyring, cryptography |
| `asr_alignment` | `whisperx` | yes, slowly | ~70: torch 2.8 + torchvision + torchaudio + the CUDA 12 stack, pyannote-audio, lightning, optuna |
| `diarization` | `diart` | yes, slowly | ~68: torch 2.13 + the CUDA 13 stack, pyannote.audio, speechbrain, optuna |
| `facial_aus` | `libreface` | yes | ~50: torch 2.0 + CUDA 11, mediapipe, dlib, opencv ×2, timm |

Two of those rows are not close calls: `human-learn` is five small pure-Python
packages, and the entry's own text about `persona_tuning` already said the
blocker was that *nothing builds a rule by example* — the dependency was never
the gate, and listing it under "will not install" hid that.

**What the group actually splits into**, which is the useful shape:

* **Downstream of a DECLINED feature (2).** `asr_alignment` feeds
  `truth_lens/prosody.py`; `facial_aus` feeds the AU stage of the same
  analyzer. Both stages exist to produce the deception gauge —
  `TruthLensCard` — which `HANDOFF.md` records as **declined, not blocked**.
  Wiring either builds toward the one card the project decided not to ship, at
  a cost of 2–6 GB of CUDA per machine.
* **A biometric decision nobody has made (1).** `diarization` is live
  who-is-speaking. `ear.py` records speaker attribution as deliberately absent
  and `HANDOFF.md` groups it with Timbre. The dependency is beside the point;
  the question is whether the product does voice biometrics.
* **No consumer, dependency irrelevant (2).** `typed_pipeline` and
  `persona_tuning`. Both capability entries already SAY so in their own gain
  strings ("nothing in the tree asks for it yet", "nothing in the tree builds
  one yet"). These belong in group D, which is where the same shape already
  lives.

The lesson is the one this file exists to enforce, turned on itself: `find_spec`
answers "is it here", and I wrote down "can it be had". Same error class as
`importable ≠ working`, one level up the supply chain, and it survived because
nothing in the entry's own "what would overturn this" section actually ran the
install — it re-ran the import.

## Consequences

* **The count is not a to-do list.** 21 dormant does not mean 21 afternoons. It
  means 4 features to design, 5 correctly-unreachable seams, 5 environments to
  provision, and 7 that each need a decision about something else first.
* Every one of the 21 is now labelled truthfully at all four surfaces the wearer
  sees — the capabilities page, the phone screen, the pack taglines, and the CLI
  — via `wires_on_install` and `runs_on`. That was the actionable half, and it
  is done.
* **Do not shrink this list by moving entries to `_BY_DESIGN` without evidence.**
  Group B belongs there on a rule the checker already applies; the rest do not,
  and filing them there would turn a measurement into a claim — the exact
  failure `HANDOFF.md` warns about two lines after the sentence this entry
  answers.

## Update — 2026-08-02, `persona_tuning` and `typed_models`: both were wired to
## consumers the product never runs

Two entries moved out of dormancy, and both had the same defect underneath —
worth recording together because the *shape* is what generalises, not either
fix.

### `persona_tuning` — a consumer the Brain never builds

Wired in #598 to `MaturityGate.tuned_confidence`. `MaturityGate` is constructed
at exactly one site, `orchestrator/orchestrator.py`, and `decisions/0001`
records that the shipped Brain never instantiates an `Orchestrator` — with
`test_the_orchestrator_is_still_not_resurrected` keeping it that way. So the
tuner ran in tests and in the simulator and nowhere the wearer could reach.

The verification error is worth naming exactly: I checked that `tune()` had a
caller and stopped one link short of asking who builds the caller.
`importable → constructed → called → reachable-from-a-surface` is four links,
and three of them held.

Fixed the way `decisions/0001` prescribes rather than by repeating its mistake:
`retention_live.py` did not resurrect the Orchestrator to get `RetentionSweep`
running, it re-hosted the plain part Brain-side.
`ai_brain/server/attention_live.py` does the same for the tuning. What was
genuinely Orchestrator-shaped — the NOVICE/APPRENTICE/RESIDENT ladder, keyed on
a pairing date the Brain does not track — stayed where it is.

It also closed a real product gap that had nothing to do with the capability:
`Brain.push_event` had no rate limit, no daily cap and no confidence bar, and
the wearer's only recourse was switching a whole cue kind off. The label it
learns from did not exist either — `dismiss_ms` is a client-side expiry timer,
so nothing ever told the Brain a card had been swatted.

### `typed_models` — the obvious home was the wrong one

`MemoryDB` has accepted a `privacy=` gate that constructs a
`models_pydantic.MemoryEvent(allowed=...)` before every write since the day it
was written, and nothing ever passed one. The obvious fix is to pass a gate at
the Brain's `MemoryDB` sites. **That would have gated nothing**, and the reason
is the useful part of this entry:

> The shipped Brain calls no `db.add_*` method at all.

Every `add_memory` caller in the tree is Orchestrator-only, the simulator, or
`ember/ceremony.burn`'s tombstone. The Brain's `MemoryDB` uses are all read
paths — the retriever, the retention sweep, the ring seed. Wiring the gate
there would have promoted the capability green while enforcing an invariant on
a path that never executes: a measurement turned into a claim, which is what
the Consequences section above warns against.

Blocking the one remaining caller would have been worse than useless. By the
time `ceremony.burn` writes its tombstone the engram is already blanked and the
source already purged; the tombstone is the wearer's *deletion receipt*, which
is precisely why that code swallows its own failures rather than leaving a
half-burn. A veiled refusal there destroys a record of an erasure.

Where the Brain actually keeps things is the **ring**. `lens_hosts.observe` and
`world_lens._remember_sighting` append to a `SemanticRingBuffer`, each site
checking `allow_capture()` first — the latter re-checking for the TOCTOU case —
and the ring itself checking nothing. That is exactly the shape
`person_guard`/`voice_guard` had before they were centralised, and exactly what
a type invariant is for. The ring now takes the same `privacy=` opt-in.

One thing that had to be got right and would have been invisible in testing:
**seeding is recall, not capture.** `_seed` re-hydrates the ring from rows
already on disk, and gating it on `allow_capture` would leave the ring empty for
a whole veiled session, so every ring lens would answer "nothing to report"
about a timeline that exists — a silence indistinguishable from an absence. It
goes through a new `restore()`. This only misbehaves on a device that happens to
be veiled at boot, which no unit test naturally reaches, so it is pinned by
reading the source of `_seed` rather than its behaviour.

### What would overturn these

For `persona_tuning`: `grep -rn "attention_live" ai_brain/server/server.py`
returning nothing, or `AttentionGate.tuning_live()` never returning True on a
Brain with a labelled history.

For `typed_models`: `SemanticRingBuffer.veil_checks` staying 0 on a live Brain
after a lens `observe()` — which would mean the tripwire is armed and nothing
crosses it, the same "dormant with extra steps" the bucket above describes.

### The lesson, stated once

Both entries were dormant for a reason no dependency could fix, and in both
cases the seam named in the catalogue was real, complete and tested. **Ask who
constructs the consumer, not whether the consumer exists** — and when the
obvious integration point turns out to be inert, that is a finding to write
down, not an obstacle to route around by wiring it anyway.

## Update — 2026-08-02, `asr_alignment` and `facial_aus`: RETIRED, not deferred

Both are removed from the catalogue and both adapters are deleted. Neither was
broken; the reworked Truth Lens made one redundant and the other unwanted.

**`facial_aus` was the one that mattered.** Four AU backends (LibreFace,
py-feat, FaceTorch, OpenFace3) sat behind a capability the wearer could install.
Installing any of them would have switched on the micro-expression channel — and
the reworked lens turns that channel off *on purpose*:
`fusion.AU_CHANNEL_REAL` is False, its weight is 0.0, it is excluded from the
confidence count, and it draws as an honest empty slot on the Testimony Thread.
`ai_brain/server/truth_live.py` states why: it "is the difference between a
delivery read and a lie detector: this surface never claims to have seen a face
twitch, because it has not."

So the entry was not a dormant capability. It was a documented, one-click way
for a wearer to turn a delivery read into a lie detector, sitting in the
catalogue with an `impact=4` next to it. That is worse than a false green: a
false green overstates what the product does, and this understated what
installing it would change.

`truth_lens/au_detector.py` is untouched and stays — it is what produces the
empty slot.

**`asr_alignment` was simply redundant.** `prosody_whisperx.word_timings()`
worked: [] without whisperx, real word timings with it. But the live channel it
was meant to sharpen — pitch, jitter, shimmer, hesitation rate, pause ratio,
speech rate, energy — is computed by `truth_lens/prosody.py` from the FFT frames
the interpreter already produces, with no dependency at all, and `truth_live.py`
feeds it directly from the endpointed segment. whisperx refined something that
already works, at ~70 packages including torch and the CUDA 12 stack.

The `asr-extra` extras group went with it, along with its references in
`PROFILES["profile-mac"]` and the "Sharp Ears" pack. Two tests in
`test_capabilities.py` caught that drift before the suite did, which is the
behaviour they exist for.

Both assertions in `test_integration_seams_pr2.py` are inverted rather than
deleted, matching how `causal_fusion` was handled in `decisions/0006`: the tests
now pin that the modules are ABSENT and that the AU channel stays off, so a
re-add is a deliberate act that trips a test rather than a quiet return.

### The general rule this establishes

Retiring a capability is a legitimate outcome and belongs beside wiring one.
The count going 73 → 71 is not a loss; two entries that could never honestly go
green stopped being on the list. **Before wiring a dormant capability, ask what
installing it would DO** — an entry whose only effect is to enable behaviour the
design deliberately refuses should be deleted, not deferred.
