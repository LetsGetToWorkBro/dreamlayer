"""test_impersonation.py — the semantic-impersonation screen (5.4).

The sandbox proves physics; this proves nothing about physics and everything
about *voice*: it flags a figment whose text imitates the device's own power /
system / security / messaging chrome, and marks shared figments as third-party.
It never blocks an install — it makes the mimicry legible.
"""
from __future__ import annotations

from dreamlayer.reality_compiler.v2 import (
    Figment, Scene, TextLine, Transition, END,
)
from dreamlayer.reality_compiler.v2.impersonation import (
    screen, voice_report, is_shared, LEXICON,
)
from dreamlayer.reality_compiler.v2.safety import safety_card, render_text


def _fig(text: str, *, origin: str | None = None) -> Figment:
    f = Figment(name="X", initial="a")
    f.add_scene(Scene(id="a", duration_sec=10.0,
                      lines=[TextLine(text, row=0)],
                      on_timeout=[Transition(target=END)]))
    if origin:
        f.meta = {"origin": origin}
    return f


# -- the screen ---------------------------------------------------------------

def test_clean_text_has_no_flags():
    assert screen(_fig("rolling — three minutes")) == []


def test_flags_power_impersonation():
    flags = screen(_fig("BATTERY CRITICAL — REMOVE GLASSES"))
    cats = {f.category for f in flags}
    assert "power" in cats and "alarm" in cats          # 'battery'+'remove glasses', 'critical'


def test_flags_fake_message_and_security():
    assert any(f.category == "message" for f in screen(_fig("Message from Maya")))
    assert any(f.category == "security" for f in screen(_fig("verify your password")))


def test_word_boundary_avoids_false_positives():
    # 'ecosystem' must not trip 'system'; 'flattery' must not trip 'battery'
    assert screen(_fig("our ecosystem is thriving")) == []
    assert screen(_fig("flattery gets you everywhere")) == []


def test_every_lexicon_category_is_reachable():
    for cat, phrases in LEXICON.items():
        got = screen(_fig(phrases[0]))
        assert any(f.category == cat for f in got), cat


# -- provenance / voice report -------------------------------------------------

def test_shared_detection():
    assert is_shared(_fig("hi", origin="shared")) is True
    assert is_shared(_fig("hi")) is False


def test_voice_report_flags_only_shared_mimicry():
    # first-party 'battery' copy (a real battery lens) is not the attack
    first = voice_report(_fig("battery low"))
    assert first["shared"] is False and first["flagged"] is False
    assert first["impersonation"]                        # still *listed*, just not flagged
    # the same text shared from a stranger IS the dangerous combination
    shared = voice_report(_fig("battery low", origin="shared"))
    assert shared["shared"] is True and shared["provenance_glyph"] is True
    assert shared["flagged"] is True


def test_clean_shared_figment_earns_the_glyph_but_no_flag():
    v = voice_report(_fig("three minutes left", origin="shared"))
    assert v["provenance_glyph"] is True and v["flagged"] is False


# -- surfaced on the safety card ----------------------------------------------

def test_safety_card_carries_the_voice_report():
    card = safety_card(_fig("SYSTEM: reboot required", origin="shared"))
    assert card["voice"]["flagged"] is True
    text = render_text(card)
    assert "imitates system messages" in text and "provenance glyph" in text
