"""
dreamlayer/memory_engine.py
MemoryEngine — pluggable on_loading callback for DreamLayerApp.

Responsibilities
----------------
- Receive a DreamLayerApp reference when the FSM enters LOADING.
- Run the configured recall pipeline (object detection, place memory, etc.).
- Call app.show_card() with the best MemoryCard result.
- On failure / low confidence, fall back to a SavedMemoryCard or timeout.

Design
------
The engine is intentionally I/O-free in its core logic so it is fully
testable.  Real AI calls (OpenAI, local model, vector DB) are injected
via RecallProvider — a simple async callable that returns a RecallResult.

Usage
-----
    from dreamlayer.memory_engine import MemoryEngine, EngineConfig

    engine = MemoryEngine(config=EngineConfig())
    app = DreamLayerApp(config=AppConfig(), on_loading=engine)
    asyncio.run(app.run())

Or inject a custom provider for testing / swapping models:

    async def my_provider(ctx: RecallContext) -> RecallResult:
        ...
    engine = MemoryEngine(provider=my_provider)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from dreamlayer.fsm import MemoryCard

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class EngineConfig:
    """Tunables for the MemoryEngine pipeline."""
    confidence_threshold: float = 0.60   # below this → fallback card
    max_results:          int   = 3      # how many recall candidates to keep
    fallback_message:     str   = "Nothing found nearby."
    log_level:            str   = "INFO"


# ---------------------------------------------------------------------------
# Recall I/O types
# ---------------------------------------------------------------------------

@dataclass
class RecallContext:
    """Snapshot of everything the provider needs to recall a memory."""
    listen_count:  int             = 0
    card_count:    int             = 0
    extra:         dict[str, Any]  = field(default_factory=dict)


@dataclass
class RecallResult:
    """
    Returned by a RecallProvider.

    card_type   : one of the known FSM card types (see MemoryCard.card_type)
    payload     : card-specific dict passed straight to MemoryCard
    confidence  : 0.0 – 1.0
    source      : label for logging / analytics ("openai", "local", "cache", …)
    """
    card_type:  str
    payload:    dict[str, Any]
    confidence: float = 1.0
    source:     str   = "engine"

    def to_memory_card(self) -> MemoryCard:
        return MemoryCard(
            card_type=self.card_type,
            payload=self.payload,
            source=self.source,
            confidence=self.confidence,
        )


RecallProvider = Callable[[RecallContext], Awaitable[RecallResult]]


# ---------------------------------------------------------------------------
# Built-in stub provider (safe default — no external deps)
# ---------------------------------------------------------------------------

async def _stub_provider(ctx: RecallContext) -> RecallResult:
    """
    Placeholder provider returned when no real provider is wired.
    Returns a low-confidence SavedMemoryCard so the fallback path fires
    and the user sees *something* rather than a hang.
    """
    return RecallResult(
        card_type="SavedMemoryCard",
        payload={"primary": "No provider configured."},
        confidence=0.0,
        source="stub",
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class MemoryEngine:
    """
    Async callable that satisfies the DreamLayerApp.on_loading signature::

        async def __call__(self, app: DreamLayerApp) -> None

    Instantiate once and pass as on_loading::

        engine = MemoryEngine(provider=my_provider)
        app = DreamLayerApp(on_loading=engine)
    """

    def __init__(
        self,
        provider: Optional[RecallProvider] = None,
        config:   Optional[EngineConfig]   = None,
    ) -> None:
        self._provider = provider or _stub_provider
        self.config    = config or EngineConfig()
        self._call_count  = 0
        self._error_count = 0
        logging.basicConfig(level=getattr(logging, self.config.log_level))

    # ------------------------------------------------------------------
    # on_loading entry point
    # ------------------------------------------------------------------

    async def __call__(self, app: Any) -> None:  # app: DreamLayerApp
        self._call_count += 1
        t0 = time.monotonic()

        ctx = RecallContext(
            listen_count=app.fsm.ctx.listen_count,
            card_count=app.fsm.ctx.card_count,
        )

        provider_crashed = False
        try:
            result = await self._provider(ctx)
        except Exception as exc:
            self._error_count += 1
            provider_crashed = True
            log.error("RecallProvider raised: %s", exc)
            result = RecallResult(
                card_type="SavedMemoryCard",
                payload={"primary": self.config.fallback_message},
                confidence=0.0,
                source="error_fallback",
            )

        elapsed = time.monotonic() - t0
        log.info(
            "Engine: %s conf=%.2f src=%s elapsed=%.3fs",
            result.card_type, result.confidence, result.source, elapsed,
        )

        # On provider crash use the error card as-is — skip confidence gating
        # so source="error_fallback" is preserved rather than rewritten to "fallback".
        if provider_crashed:
            card = result.to_memory_card()
        else:
            card = self._select_card(result)

        await app.show_card(card)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_card(self, result: RecallResult) -> MemoryCard:
        """
        Apply confidence threshold.  Below threshold → fallback card.
        Above threshold → use result as-is.
        """
        if result.confidence >= self.config.confidence_threshold:
            return result.to_memory_card()

        log.info(
            "Engine: confidence %.2f below threshold %.2f — using fallback",
            result.confidence, self.config.confidence_threshold,
        )
        return MemoryCard(
            card_type="SavedMemoryCard",
            payload={"primary": self.config.fallback_message},
            source="fallback",
            confidence=result.confidence,
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def error_count(self) -> int:
        return self._error_count

    def swap_provider(self, provider: RecallProvider) -> None:
        """Hot-swap the recall provider at runtime (useful for A/B testing)."""
        self._provider = provider
