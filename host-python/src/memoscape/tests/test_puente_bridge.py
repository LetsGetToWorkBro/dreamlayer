"""Tests for PuenteBridge Puente → LiveCaptionCard pipeline."""
import pytest
from memoscape.app.puente_bridge import PuenteBridge, _detect_language


# ---------------------------------------------------------------------------
# Language detection heuristic
# ---------------------------------------------------------------------------

def test_detect_es():
    assert _detect_language("No te preocupes, yo me encargo") == "es"

def test_detect_en():
    assert _detect_language("Don't worry, I will take care of it") == "en"

def test_detect_es_short():
    assert _detect_language("Sí, está bien") == "es"


# ---------------------------------------------------------------------------
# on_caption — basic flow
# ---------------------------------------------------------------------------

def test_on_caption_returns_live_caption_card():
    bridge = PuenteBridge()
    card = bridge.on_caption("Hola mundo", confidence=0.95)
    assert card["type"] == "LiveCaptionCard"

def test_on_caption_auto_detects_es():
    bridge = PuenteBridge()
    card = bridge.on_caption("Yo me encargo de esto")
    assert card["src_lang"] == "es"
    assert card["dst_lang"] == "en"

def test_on_caption_auto_detects_en():
    bridge = PuenteBridge()
    card = bridge.on_caption("I will take care of this")
    assert card["src_lang"] == "en"
    assert card["dst_lang"] == "es"

def test_on_caption_confidence_passthrough():
    bridge = PuenteBridge()
    card = bridge.on_caption("Hola", confidence=0.87)
    assert card["confidence"] == 0.87

def test_on_caption_speaker_in_eyebrow():
    bridge = PuenteBridge()
    card = bridge.on_caption("Buenos días", speaker="Jordan")
    assert "Jordan" in card["eyebrow"]


# ---------------------------------------------------------------------------
# on_translation — two-phase flow
# ---------------------------------------------------------------------------

def test_on_translation_populates_both_fields():
    bridge = PuenteBridge()
    card = bridge.on_translation(
        original="No te preocupes",
        translation="Don't worry",
        confidence=0.91,
    )
    assert card["original"]    == "No te preocupes"
    assert card["translation"] == "Don't worry"
    assert card["primary"]     == "Don't worry"


# ---------------------------------------------------------------------------
# Callback + last_card
# ---------------------------------------------------------------------------

def test_on_card_callback_fires():
    bridge = PuenteBridge()
    received = []
    bridge.on_card(lambda c: received.append(c))
    bridge.on_caption("Hola")
    assert len(received) == 1
    assert received[0]["type"] == "LiveCaptionCard"

def test_last_card_none_before_first_caption():
    bridge = PuenteBridge()
    assert bridge.last_card() is None

def test_last_card_reflects_most_recent():
    bridge = PuenteBridge()
    bridge.on_caption("Hola")
    bridge.on_caption("Adiós")
    assert bridge.last_card()["original"] == "Adiós"


# ---------------------------------------------------------------------------
# Empty input guard
# ---------------------------------------------------------------------------

def test_empty_text_returns_empty_dict():
    bridge = PuenteBridge()
    result = bridge.on_caption("")
    assert result == {}
