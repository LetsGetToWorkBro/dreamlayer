"""test_hud_cards.py — unit tests for hud/cards.py payload contract.

Asserts against the NEW payload shape introduced in the design-system rewrite
(commits 6b66026 / 7d490f6).  Do NOT revert to old key names.
"""
from memoscape.hud import cards


# ---------------------------------------------------------------------------
# ObjectRecallCard
# ---------------------------------------------------------------------------

def test_object_recall_payload():
    c = cards.object_recall({
        "object": "Keys",
        "place": "Kitchen table",
        "detail": "Beside blue notebook",
        "last_seen": "7:42 PM",
        "confidence": 0.86,
    })
    assert c["type"] == "ObjectRecallCard"
    # place is the hero answer; it lives in "primary"
    assert c["primary"] == "Kitchen table"
    # object name is its own key, not primary
    assert c["object"] == "Keys"
    assert "Kitchen table" in c["lines"]
    assert c["detail"] == "Beside blue n\u2026"  # truncated at 18 chars
    assert c["footer"] == "7:42 PM"              # alias of last_seen
    assert c["confidence"] == 0.86
    assert "layout" in c
    assert c["layout"]["primary"]["size"] == "hero"


def test_object_recall_positional():
    """Positional calling convention must produce same type."""
    c = cards.object_recall("Keys", place="Bedroom", confidence=0.9)
    assert c["type"] == "ObjectRecallCard"
    assert c["object"] == "Keys"
    assert c["primary"] == "Bedroom"


# ---------------------------------------------------------------------------
# CommitmentRecallCard
# ---------------------------------------------------------------------------

def test_commitment_payload():
    c = cards.commitment_recall({
        "person": "Jordan",
        "task": "Send the invoice",
        "due": "Tomorrow before noon",
        "confidence": 0.8,
    })
    assert c["type"] == "CommitmentRecallCard"
    assert c["eyebrow"] == "You promised Jordan"
    assert c["primary"] == "Send the invoice"
    assert c["footer"] == "Tomorrow before noon"  # alias of due
    assert c["confidence"] == 0.8


def test_commitment_positional():
    c = cards.commitment_recall("Alex", task="Buy milk", due="Tonight")
    assert c["type"] == "CommitmentRecallCard"
    assert c["person"] == "Alex"


# ---------------------------------------------------------------------------
# ProactiveMemoryCard
# ---------------------------------------------------------------------------

def test_proactive_footer_with_person():
    c = cards.proactive_memory({
        "summary": "You discussed the deal",
        "person": "Marcus",
        "confidence": 0.7,
    })
    assert c["footer"] == "With Marcus"
    assert c["primary"] == "You discussed the deal"


def test_proactive_footer_no_person():
    c = cards.proactive_memory({"summary": "Something happened", "person": None, "confidence": 0.6})
    assert c.get("footer") is None


# ---------------------------------------------------------------------------
# PrivacyPausedCard
# ---------------------------------------------------------------------------

def test_privacy_payload():
    c = cards.privacy_paused()
    assert c["primary"] == "Memory paused"
    assert "Nothing is being captured" in c["lines"]


# ---------------------------------------------------------------------------
# ErrorCard  — both the new name and the backwards-compat alias
# ---------------------------------------------------------------------------

def test_error_card_new_name():
    c = cards.error_card("Connection lost")
    assert c["type"] == "ErrorCard"
    assert c["primary"] == "Connection lost"


def test_error_card_alias():
    """cards.error is the backwards-compat alias for error_card."""
    c = cards.error("Connection lost")
    assert c["type"] == "ErrorCard"
    assert c["primary"] == "Connection lost"


# ---------------------------------------------------------------------------
# LowConfidenceCard
# ---------------------------------------------------------------------------

def test_low_confidence_payload():
    c = cards.low_confidence()
    assert c["type"] == "LowConfidenceCard"
    assert c["confidence"] < 0.4


# ---------------------------------------------------------------------------
# ALL_SAMPLES smoke test
# ---------------------------------------------------------------------------

def test_all_samples_have_type():
    assert len(cards.ALL_SAMPLES) == 11
    for name, payload in cards.ALL_SAMPLES.items():
        assert "type" in payload, f"ALL_SAMPLES['{name}'] missing 'type' key"
