# Memoscape

![pytest](https://github.com/LetsGetToWorkBro/memoscape/actions/workflows/pytest.yml/badge.svg)

> A private memory layer for Brilliant Labs Halo smart glasses.

Memoscape gives Halo wearers instant, on-glasses recall for the things that slip through the cracks: where you left your keys, what you promised someone, what happened last time you were in this place.

## Project layout

```
memoscape/
  host-python/          Python host — emulator bridge, real BLE bridge, memory engine
    src/memoscape/
      bridge/           BridgeBase + EmulatorBridge + RealBridge (brilliant-ble)
      memory/           SQLite DB, retrieval, proactive, privacy gate, embeddings
      pipelines/        Three-tier NLP: regex (T1) → spaCy (T2) → GPT-4o-mini (T3)
      app/              Orchestrator, intents, answer builder
      hud/              Card schema, renderer (Pillow), HUD export
      simulator/        Scenario helpers + 10 JSON fixtures
      tests/            80 pytest tests (9 modules)
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

# Run tests (no API key needed)
pytest

# Run emulator demo
python scripts/run_demo_wallet.py

# Install phone app deps
cd phone-app && npm install && npx expo start
```

### Optional: real LLM + embeddings

Set `OPENAI_API_KEY` in your environment to activate:
- **Tier 3 extraction** — GPT-4o-mini for long or ambiguous transcripts
- **Semantic embeddings** — `text-embedding-3-small` for accurate recall

Without the key, the engine falls back to regex extraction + hash-based embeddings automatically.

## Tests

80 tests across 9 modules — all pass. CI runs on every push via GitHub Actions.

```bash
pytest host-python
```

## Device day checklist

See `FIRST_DEVICE_TEST_PLAN.md`.
