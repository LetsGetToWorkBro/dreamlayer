"""test_debt_tracker.py — "Marcus owes me $20", surfaced when you see him.

Debts/favors tracked per person on the device and shown on the recall card.
Covers the grammar, the store, card surfacing, and the orchestrator flow.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.orchestrator.voice import parse_intent
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.social_lens.schema import ContactRecord, MatchResult, SocialLensResult
from dreamlayer.social_lens.enricher import ContactEnricher
from dreamlayer.truth_lens.face_embed import FaceEmbedder
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _frame(v=0.8):
    return np.full((32, 32), v, dtype=np.float32)


def _embed(v=0.8):
    return FaceEmbedder(threshold=0.40).process_frame(_frame(v)).embedding


# -- grammar ------------------------------------------------------------------

def test_debt_grammar():
    assert parse_intent("Marcus owes me $20").args == {
        "who": "Marcus", "dir": "they_owe", "what": "$20"}
    assert parse_intent("I owe Dana lunch").args == {
        "who": "Dana", "dir": "i_owe", "what": "lunch"}
    # third-person → whoever you're looking at
    assert parse_intent("she owes me twenty bucks").args["who"] is None
    # "remember" prefix still a debt, not a note
    assert parse_intent("remember Marcus owes me 50 dollars").kind == "debt"


def test_settle_grammar():
    for text, who in [("Marcus paid me back", "Marcus"),
                      ("settled up with Dana", "Dana"),
                      ("I paid Dana back", "Dana"),
                      ("we're even with Marcus", "Marcus")]:
        it = parse_intent(text)
        assert it.kind == "debt_settle" and it.args["who"] == who


def test_debt_does_not_swallow_other_intents():
    assert parse_intent("remember Maya likes climbing").kind == "note_person"
    assert parse_intent("this is my colleague Sarah").kind == "meet_person"


# -- the store + card ---------------------------------------------------------

def test_enricher_tracks_and_clears_debts():
    e = ContactEnricher()
    e.add_debt("c1", "they_owe", "$20")
    e.add_debt("c1", "i_owe", "lunch")
    assert e.get_debts("c1") == [{"dir": "they_owe", "what": "$20"},
                                 {"dir": "i_owe", "what": "lunch"}]
    e.clear_debts("c1")
    assert e.get_debts("c1") == []


def test_recall_card_shows_debts():
    c = ContactRecord(contact_id="m", name="Marcus", embedding=_embed(),
                      debts=({"dir": "they_owe", "what": "$20"},))
    card = SocialLensResult(match=MatchResult(c, 0.9, True),
                            frame_confidence=0.9).to_hud_card()
    assert card["debt"] == "owes you $20"
    assert any("owes you $20" in ln for ln in card["lines"])


# -- orchestrator flow --------------------------------------------------------

def _orc_with(name="Marcus"):
    orc = Orchestrator(FakeBridge())
    orc.social.add_contact(ContactRecord(contact_id=name.lower(), name=name,
                                         embedding=_embed()))
    return orc


def test_track_debt_by_name_then_recall():
    orc = _orc_with("Marcus")
    r = orc.handle_voice("Marcus owes me $20")
    assert r["ok"] and "owes you $20" in r["say"]
    assert orc.look_at_person(_frame())["identity"]["debt"] == "owes you $20"


def test_track_debt_in_view_then_settle():
    orc = _orc_with("Marcus")
    orc.look_at_person(_frame())                      # sets _last_person
    orc.handle_voice("she owes me a favor")           # who=None → in view
    assert orc.look_at_person(_frame())["rescue"]["debts"] == ["owes you a favor"]
    r = orc.handle_voice("Marcus paid me back")
    assert r["ok"] and "Squared up" in r["say"]
    assert orc.look_at_person(_frame())["rescue"]["debts"] == []


def test_debt_unknown_person_is_gentle():
    orc = _orc_with("Marcus")
    r = orc.handle_voice("Zelda owes me $5")
    assert r["ok"] is False and "don't know who" in r["say"].lower()


def test_debt_veil_gated():
    orc = _orc_with("Marcus")
    orc.privacy.pause()
    r = orc.handle_voice("Marcus owes me $20")
    assert r["ok"] is False
    assert orc.social._enricher.get_debts("marcus") == []
