"""Tests for GhostLayer place anchor -> WorldAnchorCard."""
import time
import pytest
from memoscape.app.dream.ghost_layer import GhostLayer, GHOST_COOLDOWN_S
from memoscape.app.recall_context import RecallContext


def make_ctx(anchors=None, place="gym_001"):
    ctx = RecallContext()
    ctx.world_anchors = anchors
    ctx.place_signature = place
    return ctx


def test_no_output_without_anchors():
    gl = GhostLayer()
    ctx = make_ctx(anchors=None)
    assert gl.tick(ctx) is None


def test_no_output_with_empty_anchors():
    gl = GhostLayer()
    ctx = make_ctx(anchors=[])
    assert gl.tick(ctx) is None


def test_emits_world_anchor_card():
    gl = GhostLayer()
    ctx = make_ctx(anchors=[{"id": "a1", "summary": "Keys here", "place": "Gym", "ts_label": "yesterday", "confidence": 0.9}])
    card = gl.tick(ctx)
    assert card is not None
    assert card.get("type") == "WorldAnchorCard"


def test_card_contains_summary():
    gl = GhostLayer()
    ctx = make_ctx(anchors=[{"id": "b1", "summary": "Wallet on shelf", "place": "Home", "ts_label": "2h ago", "confidence": 0.8}])
    card = gl.tick(ctx)
    assert card is not None
    assert "Wallet on shelf" in str(card)


def test_cooldown_suppresses_duplicate():
    gl = GhostLayer()
    ctx = make_ctx(anchors=[{"id": "c1", "summary": "Laptop bag", "place": "Office", "ts_label": "morning", "confidence": 0.75}])
    first = gl.tick(ctx)
    assert first is not None
    # second tick immediately — should be suppressed by cooldown
    second = gl.tick(ctx)
    assert second is None


def test_cooldown_expires_and_re_emits(monkeypatch):
    gl = GhostLayer()
    ctx = make_ctx(anchors=[{"id": "d1", "summary": "Charger", "place": "Desk", "ts_label": "1h ago", "confidence": 0.85}])
    gl.tick(ctx)  # prime the cooldown
    # fast-forward time past cooldown
    monkeypatch.setattr(time, "monotonic", lambda: time.monotonic.__wrapped__() + GHOST_COOLDOWN_S + 1)
    result = gl.tick(ctx)
    assert result is not None


def test_clear_cache_resets_state():
    gl = GhostLayer()
    ctx = make_ctx(anchors=[{"id": "e1", "summary": "Notebook", "place": "Library", "ts_label": "just now", "confidence": 0.95}])
    gl.tick(ctx)  # prime
    gl.clear_cache()
    # after clear, should emit again immediately
    card = gl.tick(ctx)
    assert card is not None


def test_privacy_gate_suppresses_output():
    class PausedPrivacy:
        def allow_capture(self):
            return False

    gl = GhostLayer(privacy=PausedPrivacy())
    ctx = make_ctx(anchors=[{"id": "f1", "summary": "Badge", "place": "Office", "ts_label": "now", "confidence": 0.9}])
    card = gl.tick(ctx)
    assert card is None


def test_multiple_anchors_uses_highest_confidence():
    gl = GhostLayer()
    ctx = make_ctx(anchors=[
        {"id": "g1", "summary": "Low conf item", "place": "Hall", "ts_label": "last week", "confidence": 0.4},
        {"id": "g2", "summary": "High conf item", "place": "Hall", "ts_label": "today",     "confidence": 0.95},
    ])
    card = gl.tick(ctx)
    assert card is not None
    assert "High conf item" in str(card)
