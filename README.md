# Memoscape

> A private memory layer for Brilliant Labs Halo smart glasses.

Memoscape gives Halo wearers instant, on-glasses recall for the things that slip through the cracks: where you left your keys, what you promised someone, what happened last time you were in this place.

## Project layout

```
memoscape/
  host-python/          Python host — emulator bridge, real BLE bridge, memory engine
    src/memoscape/
      bridge/           BridgeBase + EmulatorBridge + RealBridge (brilliant-ble)
      memory/           SQLite DB, retrieval, proactive, privacy gate
      pipelines/        Vision + speech extraction (mock → real swap point)
      app/              Orchestrator, intents, answer builder
      hud/              Card schema, renderer (Pillow), HUD export
      simulator/        Scenario helpers + 10 JSON fixtures
      tests/            41 pytest tests (7 modules)
  halo-lua/             Lua app for Halo display runtime
  phone-app/            Expo / React Native companion app
    app/                Expo Router screens: now, memories, settings, onboarding
    src/ui/             Design system — theme tokens, components
    src/services/       OnboardingService (5-step data-driven flow)
    src/state/          Zustand stores: onboarding, halo, memory
  scripts/              Runnable demo scripts
  assets/hud/samples/   Exported 256x256 PNG HUD card previews
```

## Quick start

```bash
# Install Python host
cd host-python
pip install -e .[dev]

# Run tests
pytest

# Run emulator demo
python scripts/run_demo_wallet.py

# Install phone app deps
cd phone-app && npm install && npx expo start
```

## Tests

41 tests across 7 modules — all pass.

```
pytest host-python/src/memoscape/tests
```

## Device day checklist

See `FIRST_DEVICE_TEST_PLAN.md`.
