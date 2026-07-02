"""
main.py — DreamLayer entry point.

Runs the full stack:
  MemoryEngine (with a real or stub provider)
    └─ DreamLayerApp (BLE + FSM)
         └─ DreamLayerFSM

Configuration via environment variables (copy .env.example → .env):

  DREAMLAYER_DEVICE      BLE address of the Frame device (optional — auto-scan if unset)
  DREAMLAYER_PROVIDER    "openai" | "stub"  (default: stub)
  DREAMLAYER_LOG_LEVEL   DEBUG | INFO | WARNING  (default: INFO)
  OPENAI_API_KEY        Required when DREAMLAYER_PROVIDER=openai
  OPENAI_MODEL          Model name  (default: gpt-4o-mini)
  OPENAI_CONFIDENCE     Fixed confidence score for OpenAI results (default: 0.85)

Usage
-----
  uv run python main.py
  DREAMLAYER_DEVICE=AA:BB:CC:DD:EE:FF uv run python main.py
  DREAMLAYER_PROVIDER=openai OPENAI_API_KEY=sk-... uv run python main.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Allow running from repo root without installing the package
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dreamlayer.app import AppConfig, DreamLayerApp
from dreamlayer.memory_engine import (
    EngineConfig,
    MemoryEngine,
    RecallContext,
    RecallResult,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider: stub (no external deps)
# ---------------------------------------------------------------------------

async def _stub_provider(ctx: RecallContext) -> RecallResult:
    """Deterministic demo card — useful for hardware bring-up without an API key."""
    return RecallResult(
        card_type="ObjectRecallCard",
        payload={
            "object":     "KEYS",
            "place":      "KITCHEN COUNTER",
            "last_seen":  "2 hours ago",
            "confidence": 0.91,
        },
        confidence=0.91,
        source="stub",
    )


# ---------------------------------------------------------------------------
# Provider: OpenAI  (lazy import — only needed when DREAMLAYER_PROVIDER=openai)
# ---------------------------------------------------------------------------

async def _openai_provider(ctx: RecallContext) -> RecallResult:
    """
    Minimal OpenAI recall provider.
    Requires:  pip install openai
    Env vars:  OPENAI_API_KEY, OPENAI_MODEL (optional), OPENAI_CONFIDENCE (optional)
    """
    try:
        from openai import AsyncOpenAI  # type: ignore
    except ImportError:
        raise RuntimeError(
            "openai package not installed. Run: uv add openai"
        )

    model      = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    confidence = float(os.getenv("OPENAI_CONFIDENCE", "0.85"))
    client     = AsyncOpenAI()  # reads OPENAI_API_KEY from env automatically

    prompt = (
        "You are a wearable memory assistant. "
        f"The user has pressed the recall button (session #{ctx.listen_count}). "
        "Return a JSON object with keys: object, place, last_seen. "
        "Be concise — each value max 4 words."
    )

    response = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=80,
        temperature=0.3,
    )

    import json
    payload = json.loads(response.choices[0].message.content)
    payload["confidence"] = confidence

    return RecallResult(
        card_type="ObjectRecallCard",
        payload=payload,
        confidence=confidence,
        source="openai",
    )


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_PROVIDERS = {
    "stub":   _stub_provider,
    "openai": _openai_provider,
}


def _load_env_file() -> None:
    """Best-effort .env loader (no python-dotenv required)."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _build_app_config() -> AppConfig:
    return AppConfig(
        device_address  = os.getenv("DREAMLAYER_DEVICE") or None,
        scan_timeout    = float(os.getenv("DREAMLAYER_SCAN_TIMEOUT",    "6.0")),
        loading_timeout = float(os.getenv("DREAMLAYER_LOAD_TIMEOUT",   "12.0")),
        reconnect_base  = float(os.getenv("DREAMLAYER_RECONNECT_BASE",  "1.0")),
        reconnect_max   = float(os.getenv("DREAMLAYER_RECONNECT_MAX",  "30.0")),
        reconnect_tries = int(  os.getenv("DREAMLAYER_RECONNECT_TRIES", "0")),
        log_level       = os.getenv("DREAMLAYER_LOG_LEVEL", "INFO").upper(),
    )


def _build_engine_config() -> EngineConfig:
    return EngineConfig(
        confidence_threshold = float(os.getenv("DREAMLAYER_CONFIDENCE", "0.60")),
        fallback_message     = os.getenv("DREAMLAYER_FALLBACK", "Nothing found nearby."),
        log_level            = os.getenv("DREAMLAYER_LOG_LEVEL", "INFO").upper(),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _main() -> None:
    _load_env_file()

    log_level = os.getenv("DREAMLAYER_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    provider_name = os.getenv("DREAMLAYER_PROVIDER", "stub").lower()
    provider = _PROVIDERS.get(provider_name)
    if provider is None:
        log.error("Unknown provider %r. Choose: %s", provider_name, list(_PROVIDERS))
        sys.exit(1)

    app_cfg    = _build_app_config()
    engine_cfg = _build_engine_config()
    engine     = MemoryEngine(provider=provider, config=engine_cfg)
    app        = DreamLayerApp(config=app_cfg, on_loading=engine)

    log.info("DreamLayer starting  provider=%s  device=%s",
             provider_name, app_cfg.device_address or "(auto-scan)")

    try:
        await app.run()
    except KeyboardInterrupt:
        log.info("Interrupted — stopping.")
        app.stop()


if __name__ == "__main__":
    asyncio.run(_main())
