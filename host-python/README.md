# host-python — the DreamLayer engine

The Python side of DreamLayer: the **phone hub** (orchestrator, memory,
privacy gate, the lenses) and the **Mac mini Brain** (indexed knowledge + AI +
control panel) live here as one installable package, `dreamlayer`.

> New here? Start with the top-level [`../README.md`](../README.md) for the
> product, and [`../docs/TESTING.md`](../docs/TESTING.md) to run it.

## Install

```bash
pip install -e .[dev]       # editable install + pytest, pytest-asyncio, lupa
python -m pytest -q         # the full suite (1,606 tests)
```

Requires Python 3.11+. The runtime is largely standard-library; heavier
providers (vision models, Ollama) are optional and plug in behind seams.

## Run the Mac Brain

```bash
python -m dreamlayer.ai_brain.server --token rune-birch
# → control panel + phone API at http://<lan-ip>:7777/
```

See [`../docs/AI_BRAIN.md`](../docs/AI_BRAIN.md) for the tiered brain and the
three switches (Mac mini / Cloud / Incognito), and
[`../docs/OLLAMA_SETUP.md`](../docs/OLLAMA_SETUP.md) for local models.

## The package — `src/dreamlayer/`

```
orchestrator/       central coordinator + the three brain switches
ai_brain/           tiered router → device / Mac mini / cloud
  ├── router.py     preference-ordered tiers; cloud + local-only gates
  ├── remote.py     the Mac mini tier (RemoteVision/Knowledge brains)
  ├── cloud.py      opt-in cloud tier
  └── server/       the Mac Brain: index · control panel · pairing · macOS sources
lucid_recall/       query router → SocialLens / MemoryIndex → HUD card
object_lens/        Oracle + Label — look at a thing → a contextual panel
social_lens/        recognise your own people; consent-first name capture
truth_lens/         9-stage multimodal deception analysis
dream_mode/         the ambient loop, Ghost Layer, world-anchored cards
rem/                the sleep cycle: dream, consolidate, morning reel
reality_compiler/   v2 Rehearsal → signed Figment → fixed on-glass stage
confluence/         bonds, the entangled sky, TinCan, weather gifts
hud/                card definitions, mirror renderer, goldens, earcon map
demo/               the emissive-overlay demo/film pipeline (python -m dreamlayer.demo)
memory/             anchors, storage, retrieval, ranking
pipelines/          audio · vision · IMU · place-context ingestion
bridge/             BLE protocol, hardware translation, the Lua raster harness
simulator/          a host-side stand-in for the glasses
rosetta.py          visual translation (Rosetta = eye; Puente = ear/voice)
lenses.py           the six-lens registry (the mental model, in code)
pairing.py          one code → phone + Brain + glasses
```

## Design notes

- **Seams, not hard deps.** Vision, knowledge, and external data sources are
  injected callables (see the `PolledSource` pattern and the provider
  registries) so any model or device drops in without touching the core.
- **Privacy is enforced here.** `allow_capture()` / the Privacy Veil gate every
  lens; `meta.private` never leaves the device; the cloud tier is reached only
  behind an explicit opt-in. See [`../docs/PRIVACY_MODEL.md`](../docs/PRIVACY_MODEL.md).
- **Tests are the spec.** Run `python -m pytest` (not bare `pytest`). Server
  tests exercise real localhost HTTP; Lua interop tests use `lupa`.
