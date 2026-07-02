# DreamLayer — Implementation Plan

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
- Real BLE packet framing / MTU tuning (`real_bridge.py` marked TODO)
- On-device camera/mic/IMU real behavior (Lua capture modules are wrappers)
- Display color/gamma calibration vs real panel
- BLE latency + battery profiling

## Immediate next tasks
1. Wire `real_bridge.py` to `brilliant-ble` once SDK pinned
2. Replace MockEmbeddingProvider with real provider behind `EmbeddingProvider`
3. Replace mock vision/speech with real model calls
4. Build out phone-app screens beyond scaffold
