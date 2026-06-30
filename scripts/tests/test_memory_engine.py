"""
pytest tests for memoscape/memory_engine.py.
All pure — no network, no BLE hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from memoscape.memory_engine import (
    EngineConfig,
    MemoryEngine,
    RecallContext,
    RecallResult,
    _stub_provider,
)
from memoscape.fsm import MemoryCard, State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_app(
    listen_count: int = 1,
    card_count:   int = 0,
    fsm_state:    State = State.LOADING,
) -> MagicMock:
    """Minimal MemoscapeApp stand-in the engine can call show_card() on."""
    app = MagicMock()
    app.fsm.ctx.listen_count = listen_count
    app.fsm.ctx.card_count   = card_count
    app.fsm.state            = fsm_state
    app.show_card            = AsyncMock()
    return app


def _good_result(
    card_type:  str   = "ObjectRecallCard",
    confidence: float = 0.92,
    source:     str   = "test",
) -> RecallResult:
    return RecallResult(
        card_type=card_type,
        payload={"object": "KEYS", "place": "KITCHEN", "last_seen": "2h", "confidence": confidence},
        confidence=confidence,
        source=source,
    )


# ---------------------------------------------------------------------------
# EngineConfig
# ---------------------------------------------------------------------------

class TestEngineConfig:
    def test_defaults(self):
        cfg = EngineConfig()
        assert cfg.confidence_threshold == 0.60
        assert cfg.max_results == 3
        assert cfg.fallback_message == "Nothing found nearby."

    def test_custom(self):
        cfg = EngineConfig(confidence_threshold=0.80, max_results=5)
        assert cfg.confidence_threshold == 0.80
        assert cfg.max_results == 5


# ---------------------------------------------------------------------------
# RecallResult.to_memory_card
# ---------------------------------------------------------------------------

class TestRecallResult:
    def test_to_memory_card_fields(self):
        r = _good_result()
        card = r.to_memory_card()
        assert isinstance(card, MemoryCard)
        assert card.card_type  == "ObjectRecallCard"
        assert card.confidence == 0.92
        assert card.source     == "test"
        assert card.payload["object"] == "KEYS"

    def test_is_high_confidence(self):
        assert _good_result(confidence=0.75).to_memory_card().is_high_confidence()
        assert not _good_result(confidence=0.74).to_memory_card().is_high_confidence()


# ---------------------------------------------------------------------------
# Stub provider
# ---------------------------------------------------------------------------

class TestStubProvider:
    @pytest.mark.asyncio
    async def test_returns_recall_result(self):
        result = await _stub_provider(RecallContext())
        assert isinstance(result, RecallResult)
        assert result.confidence == 0.0
        assert result.source == "stub"


# ---------------------------------------------------------------------------
# MemoryEngine.__call__ — happy path
# ---------------------------------------------------------------------------

class TestMemoryEngineCall:
    @pytest.mark.asyncio
    async def test_high_confidence_shows_result_card(self):
        """Provider returns high-confidence result → show_card called with it."""
        async def provider(ctx): return _good_result(confidence=0.92)

        engine = MemoryEngine(provider=provider)
        app    = _mock_app()
        await engine(app)

        app.show_card.assert_called_once()
        card: MemoryCard = app.show_card.call_args[0][0]
        assert card.card_type  == "ObjectRecallCard"
        assert card.confidence == 0.92
        assert card.source     == "test"

    @pytest.mark.asyncio
    async def test_low_confidence_shows_fallback_card(self):
        """Provider returns below-threshold → fallback SavedMemoryCard."""
        async def provider(ctx): return _good_result(confidence=0.40)

        engine = MemoryEngine(
            provider=provider,
            config=EngineConfig(confidence_threshold=0.60),
        )
        app = _mock_app()
        await engine(app)

        card: MemoryCard = app.show_card.call_args[0][0]
        assert card.card_type == "SavedMemoryCard"
        assert card.source    == "fallback"

    @pytest.mark.asyncio
    async def test_exactly_at_threshold_passes(self):
        """Confidence equal to threshold is accepted (>=)."""
        async def provider(ctx): return _good_result(confidence=0.60)

        engine = MemoryEngine(
            provider=provider,
            config=EngineConfig(confidence_threshold=0.60),
        )
        app = _mock_app()
        await engine(app)

        card: MemoryCard = app.show_card.call_args[0][0]
        assert card.card_type == "ObjectRecallCard"

    @pytest.mark.asyncio
    async def test_call_count_increments(self):
        async def provider(ctx): return _good_result()
        engine = MemoryEngine(provider=provider)
        app = _mock_app()
        await engine(app)
        await engine(app)
        assert engine.call_count == 2

    @pytest.mark.asyncio
    async def test_context_passed_to_provider(self):
        """Engine builds RecallContext from app.fsm.ctx correctly."""
        received: list[RecallContext] = []

        async def provider(ctx):
            received.append(ctx)
            return _good_result()

        engine = MemoryEngine(provider=provider)
        app = _mock_app(listen_count=7, card_count=3)
        await engine(app)

        assert received[0].listen_count == 7
        assert received[0].card_count   == 3

    @pytest.mark.asyncio
    async def test_show_card_called_exactly_once(self):
        async def provider(ctx): return _good_result()
        engine = MemoryEngine(provider=provider)
        app = _mock_app()
        await engine(app)
        assert app.show_card.call_count == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestMemoryEngineErrors:
    @pytest.mark.asyncio
    async def test_provider_exception_shows_fallback_card(self):
        """Provider crash → error_fallback card, not an unhandled exception."""
        async def broken_provider(ctx):
            raise RuntimeError("model exploded")

        engine = MemoryEngine(
            provider=broken_provider,
            config=EngineConfig(fallback_message="Try again later."),
        )
        app = _mock_app()
        await engine(app)

        card: MemoryCard = app.show_card.call_args[0][0]
        assert card.card_type == "SavedMemoryCard"
        assert card.source    == "error_fallback"
        assert card.payload["primary"] == "Try again later."

    @pytest.mark.asyncio
    async def test_error_count_increments_on_exception(self):
        async def broken_provider(ctx): raise ValueError("oops")
        engine = MemoryEngine(provider=broken_provider)
        app = _mock_app()
        await engine(app)
        await engine(app)
        assert engine.error_count == 2

    @pytest.mark.asyncio
    async def test_show_card_still_called_after_provider_crash(self):
        """Even on crash, show_card is called exactly once (fallback)."""
        async def broken_provider(ctx): raise Exception("boom")
        engine = MemoryEngine(provider=broken_provider)
        app = _mock_app()
        await engine(app)
        assert app.show_card.call_count == 1


# ---------------------------------------------------------------------------
# _select_card
# ---------------------------------------------------------------------------

class TestSelectCard:
    def _engine(self, threshold=0.60, fallback="Nothing."):
        return MemoryEngine(config=EngineConfig(
            confidence_threshold=threshold,
            fallback_message=fallback,
        ))

    def test_above_threshold_returns_result(self):
        engine = self._engine(threshold=0.60)
        card = engine._select_card(_good_result(confidence=0.80))
        assert card.card_type == "ObjectRecallCard"

    def test_below_threshold_returns_fallback(self):
        engine = self._engine(threshold=0.60, fallback="Nothing nearby.")
        card = engine._select_card(_good_result(confidence=0.50))
        assert card.card_type == "SavedMemoryCard"
        assert card.payload["primary"] == "Nothing nearby."
        assert card.source == "fallback"

    def test_zero_confidence_always_fallback(self):
        engine = self._engine()
        card = engine._select_card(RecallResult(
            card_type="ObjectRecallCard",
            payload={},
            confidence=0.0,
        ))
        assert card.card_type == "SavedMemoryCard"

    def test_full_confidence_passes(self):
        engine = self._engine()
        card = engine._select_card(RecallResult(
            card_type="ObjectRecallCard",
            payload={"object": "WALLET"},
            confidence=1.0,
        ))
        assert card.card_type == "ObjectRecallCard"


# ---------------------------------------------------------------------------
# swap_provider
# ---------------------------------------------------------------------------

class TestSwapProvider:
    @pytest.mark.asyncio
    async def test_swap_changes_result(self):
        async def provider_a(ctx):
            return RecallResult(card_type="ObjectRecallCard", payload={"object": "KEYS"}, confidence=0.9)

        async def provider_b(ctx):
            return RecallResult(card_type="ObjectRecallCard", payload={"object": "WALLET"}, confidence=0.9)

        engine = MemoryEngine(provider=provider_a)
        app = _mock_app()

        await engine(app)
        card_a: MemoryCard = app.show_card.call_args[0][0]
        assert card_a.payload["object"] == "KEYS"

        engine.swap_provider(provider_b)
        app2 = _mock_app()
        await engine(app2)
        card_b: MemoryCard = app2.show_card.call_args[0][0]
        assert card_b.payload["object"] == "WALLET"


# ---------------------------------------------------------------------------
# Integration: engine wired into a real MemoscapeApp
# ---------------------------------------------------------------------------

class TestEngineIntegration:
    @pytest.mark.asyncio
    async def test_engine_wired_to_app_reaches_card_state(self):
        """Full integration: engine as on_loading drives FSM to CARD."""
        from memoscape.app import AppConfig, MemoscapeApp
        from memoscape.fsm import Event

        async def provider(ctx):
            return RecallResult(
                card_type="ObjectRecallCard",
                payload={"object": "KEYS", "place": "KITCHEN",
                         "last_seen": "2h", "confidence": 0.91},
                confidence=0.91,
                source="test",
            )

        engine = MemoryEngine(provider=provider)
        cfg    = AppConfig(device_address="AA:BB:CC:DD:EE:FF", log_level="WARNING")
        app    = MemoscapeApp(config=cfg, on_loading=engine)

        app._fsm.send(Event.BLE_CONNECT)
        app._fsm.send(Event.BUTTON_SINGLE)
        app._fsm.send(Event.LOADING_START)
        assert app.state == State.LOADING

        await app._run_loading()

        assert app.state == State.CARD
        assert app.fsm.ctx.current_card is not None
        assert app.fsm.ctx.current_card.card_type == "ObjectRecallCard"

    @pytest.mark.asyncio
    async def test_engine_fallback_still_reaches_card_state(self):
        """Even with a low-confidence provider, FSM ends up at CARD (fallback card)."""
        from memoscape.app import AppConfig, MemoscapeApp
        from memoscape.fsm import Event

        async def weak_provider(ctx):
            return RecallResult(
                card_type="ObjectRecallCard",
                payload={},
                confidence=0.10,  # below threshold
            )

        engine = MemoryEngine(provider=weak_provider)
        cfg    = AppConfig(device_address="AA:BB:CC:DD:EE:FF", log_level="WARNING")
        app    = MemoscapeApp(config=cfg, on_loading=engine)

        app._fsm.send(Event.BLE_CONNECT)
        app._fsm.send(Event.BUTTON_SINGLE)
        app._fsm.send(Event.LOADING_START)
        await app._run_loading()

        assert app.state == State.CARD
        assert app.fsm.ctx.current_card.card_type == "SavedMemoryCard"
