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
dependency that will not install, or a claimed interface the seam does not fit.
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

### C — dependency will not install in this environment (5)

`asr_alignment` (whisperx), `diarization` (diart), `facial_aus`
(libreface/pyfeat/facetorch), `persona_tuning` (hulearn), `typed_pipeline`
(pydantic_ai). A wire written against a library that cannot be imported cannot
be tested, and an untested wire against an optional dependency is precisely the
`importable ≠ working` failure this repo keeps finding. Deferred on evidence,
not on preference.

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

* **`structured_output`** — the seam is LIVE (`brain_rc.py` builds
  `LLMIntentParser` on the compose path) and `outlines`/`instructor` are both
  installed; they are simply never called. Wiring them is not a line change:
  `outlines` constrains a local sampler and needs direct model access, while the
  suggester here is `backend.chat(prompt) -> str`, an Ollama HTTP call;
  `instructor` patches an OpenAI-compatible *client*, and there is no client
  object to patch. Either path restructures how the Brain talks to its local
  model — on a path that already works, whose current design already guarantees
  schema-legality by parsing the model's restatement with the deterministic
  matchers. The gain would be fewer fallbacks, not correctness.

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
C: python -c "import whisperx"    (etc.)
   → an importable dependency moves that row from C into the real work
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
