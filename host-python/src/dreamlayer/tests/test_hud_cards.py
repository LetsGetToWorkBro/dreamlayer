"""test_hud_cards.py — unit tests for hud/cards.py payload contract.

Asserts against the payload shape post design-system rewrite
(commits 6b66026 / 7d490f6).  Do NOT revert to old key names.
"""
from dreamlayer.hud import cards


# ---------------------------------------------------------------------------
# ObjectRecallCard
# ---------------------------------------------------------------------------

def test_object_recall_payload():
    c = cards.object_recall({
        "object":     "Keys",
        "place":      "Kitchen table",
        "detail":     "Beside blue notebook",
        "last_seen":  "7:42 PM",
        "confidence": 0.86,
    })
    assert c["type"] == "ObjectRecallCard"
    assert c["primary"] == "Keys"
    assert c["place"] == "Kitchen table"
    assert "Kitchen table" in c["lines"]
    assert c["detail"] == "Beside blue noteb\u2026"
    assert c["footer"] == "7:42 PM"
    assert c["confidence"] == 0.86
    assert "layout" in c
    assert c["layout"]["primary"]["size"] == "hero"


def test_object_recall_positional():
    c = cards.object_recall("Keys", place="Bedroom", confidence=0.9)
    assert c["type"] == "ObjectRecallCard"
    assert c["primary"] == "Keys"
    assert c["place"] == "Bedroom"


# ---------------------------------------------------------------------------
# CommitmentRecallCard
# ---------------------------------------------------------------------------

def test_commitment_payload():
    c = cards.commitment_recall({
        "person":     "Jordan",
        "task":       "Send the invoice",
        "due":        "Tomorrow before noon",
        "confidence": 0.8,
    })
    assert c["type"] == "CommitmentRecallCard"
    assert c["eyebrow"] == "You promised Jordan"
    assert c["primary"] == "Send the invoice"
    assert c["footer"] == "Tomorrow before noon"
    assert c["confidence"] == 0.8


def test_commitment_positional():
    c = cards.commitment_recall("Alex", task="Buy milk", due="Tonight")
    assert c["type"] == "CommitmentRecallCard"
    assert c["person"] == "Alex"
    assert c["primary"] == "Buy milk"


# ---------------------------------------------------------------------------
# ProactiveMemoryCard
# ---------------------------------------------------------------------------

def test_proactive_footer_with_person():
    c = cards.proactive_memory({
        "summary":    "You discussed the deal",
        "person":     "Marcus",
        "confidence": 0.7,
    })
    assert c["footer"] == "With Marcus"
    assert c["primary"] == "You discussed the deal"


def test_proactive_footer_no_person():
    c = cards.proactive_memory({
        "summary":    "Something happened",
        "person":     None,
        "confidence": 0.6,
    })
    assert c.get("footer") is None


# ---------------------------------------------------------------------------
# PrivacyVeilCard
# ---------------------------------------------------------------------------

def test_privacy_payload():
    c = cards.privacy_veil()
    assert c["primary"] == "Privacy Veil"
    assert "Nothing is being captured" in c["lines"]


# ---------------------------------------------------------------------------
# ErrorCard — both the new name and the backwards-compat alias
# ---------------------------------------------------------------------------

def test_error_card_new_name():
    c = cards.error_card("Connection lost")
    assert c["type"] == "ErrorCard"
    assert c["primary"] == "Connection lost"


def test_error_card_alias():
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
# Conversation ledger cards
# ---------------------------------------------------------------------------

def test_spoken_caption_payload():
    c = cards.spoken_caption("Marcus Reyes", "let's sign the lease")
    assert c["type"] == "SpokenCaptionCard"
    assert c["primary"] == "let's sign the lease"
    assert c["eyebrow"] == "MARCUS"           # first name, uppercased
    assert c["dismiss_ms"] == 0               # stays until replaced


def test_spoken_caption_truncates_long_lines():
    c = cards.spoken_caption("", "x" * 200)
    assert len(c["primary"]) <= 96 and c["primary"].endswith("…")
    assert c["eyebrow"] == "HEARD"            # no speaker → generic label


def test_person_dossier_payload():
    c = cards.person_dossier({
        "person": "Priya", "known": True, "exchanges": 4,
        "last_seen_ago": "20 min ago", "last_line": "ping me after lunch",
        "topics": ["budget", "q3", "hiring"],
    })
    assert c["type"] == "PersonDossierCard"
    assert c["primary"] == "Priya"
    assert "20 min ago" in c["headline"]
    assert "budget" in c["detail"]
    assert c["footer"] == "ping me after lunch"


# ---------------------------------------------------------------------------
# ALL_SAMPLES smoke test
# ---------------------------------------------------------------------------

def test_all_samples_have_type():
    # 11 original + 3 new (commitment_drift, time_scrub_node, deviation_alert)
    assert len(cards.ALL_SAMPLES) >= 14
    for name, payload in cards.ALL_SAMPLES.items():
        assert "type" in payload, f"ALL_SAMPLES['{name}'] missing 'type' key"
