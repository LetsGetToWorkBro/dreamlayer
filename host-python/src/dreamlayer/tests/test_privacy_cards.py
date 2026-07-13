"""Tests for the three new privacy card factories and LiveCaptionCard."""
from dreamlayer.hud.cards import (
    forget_last_card,
    private_zone_card,
    consent_required_card,
    live_caption_card,
    ALL_SAMPLES,
)


# ---------------------------------------------------------------------------
# ForgetLastCard
# ---------------------------------------------------------------------------

def test_forget_last_card_type():
    c = forget_last_card("House keys")
    assert c["type"] == "ForgetLastCard"

def test_forget_last_card_required_fields():
    c = forget_last_card("House keys")
    assert c["label"] == "House keys"
    assert "House keys" in c["primary"]
    assert c["dismiss_ms"] == 0   # must not auto-dismiss
    assert "layout" in c
    assert "shield" in c["layout"]

def test_forget_last_card_default_label():
    c = forget_last_card()
    assert "last memory" in c["primary"]


# ---------------------------------------------------------------------------
# PrivateZoneCard
# ---------------------------------------------------------------------------

def test_private_zone_card_type():
    c = private_zone_card("Home office")
    assert c["type"] == "PrivateZoneCard"

def test_private_zone_card_required_fields():
    c = private_zone_card("Hospital")
    assert c["zone"] == "Hospital"
    assert c["dismiss_ms"] == 0
    assert "CAPTURE SUSPENDED" in c["eyebrow"]
    assert "layout" in c


# ---------------------------------------------------------------------------
# ConsentRequiredCard
# ---------------------------------------------------------------------------

def test_consent_required_card_type():
    c = consent_required_card("Calendar access")
    assert c["type"] == "ConsentRequiredCard"

def test_consent_required_card_fields():
    c = consent_required_card("Calendar access")
    assert c["context"] == "Calendar access"
    assert c["dismiss_ms"] == 0
    assert "CONSENT REQUIRED" in c["eyebrow"]
    assert "lock" in c["layout"]


# ---------------------------------------------------------------------------
# LiveCaptionCard
# ---------------------------------------------------------------------------

def test_live_caption_card_type():
    c = live_caption_card(original="Hola", translation="Hello", src_lang="es", dst_lang="en")
    assert c["type"] == "LiveCaptionCard"

def test_live_caption_card_fields():
    c = live_caption_card(
        original="No te preocupes",
        translation="Don't worry",
        src_lang="es",
        dst_lang="en",
        confidence=0.92,
        speaker="Jordan",
    )
    assert c["original"]    == "No te preocupes"
    assert c["translation"] == "Don't worry"
    assert c["primary"]     == "Don't worry"   # translation is hero
    assert c["footer"]      == "No te preocupes"  # original is footer
    assert "Jordan" in c["eyebrow"]
    assert "ES" in c["eyebrow"]
    assert "EN" in c["eyebrow"]
    assert c["confidence"]  == 0.92
    assert c["dismiss_ms"]  == 0   # live caption stays open


# ---------------------------------------------------------------------------
# ALL_SAMPLES includes all new cards
# ---------------------------------------------------------------------------

def test_all_samples_has_new_cards():
    for key in ("forget_last", "private_zone", "consent_required", "live_caption"):
        assert key in ALL_SAMPLES, f"Missing key: {key}"
        assert ALL_SAMPLES[key]["type"] is not None
