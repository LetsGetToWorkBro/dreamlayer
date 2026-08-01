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

For 4 of the 21 that is roughly true and the work is real. For the other 17 the
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
| `event_bus` | `MeshManager` is constructed nowhere in the tree. `MeshEventBus` wraps one; with no mesh there are no packets to fan out. |
| `object_tracking` | Nothing emits per-frame centroids. `SupervisionTracker.update(centroids)` is referenced only by its own tests, and its natural partner `LostFoundScene` keys its ledger by LABEL rather than tracked identity — and is not constructed either. |
| `wasm_plugins` | Needs a `.wasm`-guest package format. `store.py`'s own docstring already names the component host as *"the forward path a `.wasm`-guest package format targets"*; today's plugins ship Python module code. |
| `extism_plugins` | The same missing format, a second runtime. |

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
   → a construction outside confluence/mesh.py means event_bus is wireable
C: python -c "import whisperx"    (etc.)
   → an importable dependency moves that row from C into the real work
D: grep -n "def register" -A 3 host-python/src/dreamlayer/hud/renderer.py
   → a one-argument callback would make skia_render's original claim true
```

For the whole entry: `python -m dreamlayer.capabilities` and the counts in
`capability_reachability.py`. If wired rises above 39 without this file
changing, the file is stale.

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
