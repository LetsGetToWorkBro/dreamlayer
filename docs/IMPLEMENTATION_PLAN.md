# DreamLayer — Implementation Plan

*(Status 2026-07: this plan dates from the original scaffold and undercounts
the current tree — it predates Halo Cinema v1/v2, Reality Compiler v2
figments, the AI Brain, plugins/lenses, Confluence, and reality-core. The
inventory below is kept as a record of that baseline; see
`docs/ARCHITECTURE.md` and the docs index for current state.)*

## Complete in this repo
- Full product + architecture + HUD + privacy docs
- Lua: state machine, events, display primitives/layout/typography/palette,
  renderer, all 11 cards, animations, BLE protocol abstraction, capture stubs,
  power/settings, lib utils
- Python: BridgeBase + EmulatorBridge + RealBridge stub, HUD mirror + export,
  SQLite memory engine (schema/models/retrieval/summarizer/proactive/privacy),
  mock embeddings, mock pipelines, orchestrator/intents/answer_builder
- Fixtures for all 4 demos
- 5 test modules (cards, recall, privacy, scenarios, emulator bridge)
- 6 runnable scripts (emulator, 3 demos, export, tests)
- Phone-app scaffold (Expo Router) with theme + services + components

## Blocked until hardware
- On-hardware validation of BLE packet framing / MTU tuning (`real_bridge.py`
  now implements framing over `brilliant-ble`/`brilliant-msg`; untested on
  real glass)
- On-device camera/mic/IMU real behavior (Lua capture modules are wrappers)
- Display color/gamma calibration vs real panel
- BLE latency + battery profiling

## Immediate next tasks — all since shipped (2026-07)
1. ~~Wire `real_bridge.py` to `brilliant-ble` once SDK pinned~~ — done
   (`bridge/real_bridge.py`)
2. ~~Replace MockEmbeddingProvider with real provider behind
   `EmbeddingProvider`~~ — done (`memory/embedder_local.py`
   LocalEmbeddingProvider, plus OpenAIEmbeddingProvider; mock remains the
   no-extras fallback)
3. ~~Replace mock vision/speech with real model calls~~ — done behind optional
   extras (`object_lens/classify_backends.py` YOLO→moondream→CLIP,
   `orchestrator/asr_faster_whisper.py`; mock pipelines remain the offline
   seams)
4. ~~Build out phone-app screens beyond scaffold~~ — done (20+ screens under
   `phone-app/app/`)
