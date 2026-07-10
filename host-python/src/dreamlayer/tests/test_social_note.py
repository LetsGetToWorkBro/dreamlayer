"""test_social_note.py — "jot a note about a person, on the spot."

    "Juno, remember Maya's into rock climbing"
        → appended to Maya's contact → shown the next time you see her.

Covers the grammar (note_person intent), the note store (append/dedupe/cap +
latest), the card surfacing, and the orchestrator flow (by name, whoever
you're looking at, unknown name, nobody in view, incognito).
"""
from __future__ import annotations

import numpy as np

from dreamlayer.orchestrator.voice import parse_intent
from dreamlayer.social_lens import SocialLens
from dreamlayer.social_lens.schema import ContactRecord, MatchResult, SocialLensResult
from dreamlayer.social_lens.enricher import ContactEnricher
from dreamlayer.truth_lens.face_embed import FaceEmbedder
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _frame(v=0.8):
    return np.full((32, 32), v, dtype=np.float32)


def _embed(v=0.8):
    au = FaceEmbedder(threshold=0.40).process_frame(_frame(v))
    return au.embedding


def _contact(cid="maya", name="Maya", v=0.8, **kw):
    return ContactRecord(contact_id=cid, name=name, embedding=_embed(v), **kw)


# -- grammar ------------------------------------------------------------------

def test_note_by_name():
    it = parse_intent("Hey Juno, remember Maya's into rock climbing")
    assert it.kind == "note_person"
    assert it.args["who"] == "Maya" and it.args["note"] == "into rock climbing"


def test_note_various_phrasings():
    cases = {
        "note that Priya has two kids": ("Priya", "has two kids"),
        "remember Marcus works at Google": ("Marcus", "works at Google"),
        "remember Dana loves oat milk lattes": ("Dana", "loves oat milk lattes"),
    }
    for text, (who, note) in cases.items():
        it = parse_intent(text)
        assert it.kind == "note_person", text
        assert it.args["who"] == who and it.args["note"] == note, (text, it.args)


def test_note_about_the_person_in_view():
    it = parse_intent("remember she's into climbing")
    assert it.kind == "note_person" and it.args["who"] is None
    assert it.args["note"] == "into climbing"
    assert parse_intent("remember he works nights").args["who"] is None


def test_wearer_statements_are_not_person_notes():
    # "remember that I..." is about you, not a contact — left alone
    assert parse_intent("remember that I'm allergic to shellfish").kind != "note_person"
    assert parse_intent("remember I need milk").kind != "note_person"
    # "remember to <do>" is a reminder, not a note
    assert parse_intent("remember to call the dentist").kind != "note_person"


# -- the note store -----------------------------------------------------------

def test_append_note_keeps_history_and_dedupes():
    e = ContactEnricher()
    e.append_note("c1", "likes climbing")
    e.append_note("c1", "has two kids")
    e.append_note("c1", "likes climbing")             # dupe → moved to newest
    notes = e.get_notes("c1")
    assert notes == "has two kids • likes climbing"
    assert e.latest_note(notes) == "likes climbing"


def test_append_note_caps_length_dropping_oldest():
    e = ContactEnricher()
    for i in range(60):
        e.append_note("c1", f"fact number {i}")
    notes = e.get_notes("c1")
    assert len(notes) <= ContactEnricher.NOTES_MAX
    assert "fact number 59" in notes and "fact number 0" not in notes


# -- the card surfaces the latest note ---------------------------------------

def test_recall_card_shows_the_note():
    c = _contact(notes="climbs V6 • into rock climbing")
    card = SocialLensResult(match=MatchResult(c, 0.92, True),
                            frame_confidence=0.9).to_hud_card()
    assert card["note"] == "“into rock climbing”"
    assert any("rock climbing" in ln for ln in card["lines"])


# -- SocialLens.add_note ------------------------------------------------------

def test_add_note_by_name_then_recall_shows_it():
    fr = SocialLens([_contact()])
    got = fr.add_note("into rock climbing", who="Maya")
    assert got is not None and "into rock climbing" in (got.notes or "")
    # the very next recall shows it
    res = fr.identify(_frame(0.8))
    assert res.match is not None
    assert res.match.contact.notes and "rock climbing" in res.match.contact.notes


def test_add_note_unknown_name_returns_none():
    fr = SocialLens([_contact()])
    assert fr.add_note("likes tea", who="Nobody") is None


def test_add_note_to_whoever_you_just_looked_at():
    fr = SocialLens([_contact()])
    fr.identify(_frame(0.8))                          # look at Maya
    got = fr.add_note("just got a puppy")             # who=None → last identified
    assert got is not None and "puppy" in got.notes


# -- orchestrator flow --------------------------------------------------------

def _orc_with_maya():
    orc = Orchestrator(FakeBridge())
    orc.social.add_contact(_contact())
    return orc


def test_orchestrator_note_by_name():
    orc = _orc_with_maya()
    r = orc.handle_voice("Hey Juno, remember Maya loves oat milk")
    assert r["intent"] == "note_person" and r["ok"] is True
    assert r["who"] == "Maya" and "oat milk" in orc.social._enricher.get_notes("maya")


def test_orchestrator_note_in_view_after_looking():
    orc = _orc_with_maya()
    orc.look_at_person(_frame(0.8))                   # sets _last_person
    r = orc.handle_voice("remember she's into climbing")
    assert r["ok"] is True and r["who"] == "Maya"
    assert "into climbing" in orc.social._enricher.get_notes("maya")


def test_orchestrator_note_in_view_without_looking_is_gentle():
    orc = _orc_with_maya()
    r = orc.handle_voice("remember she likes tea")
    assert r["ok"] is False and "Look at someone" in r["say"]


def test_orchestrator_note_unknown_name():
    orc = _orc_with_maya()
    r = orc.handle_voice("remember Zoltan plays chess")
    assert r["ok"] is False and "don't know who" in r["say"].lower()


def test_orchestrator_note_blocked_while_capture_veiled():
    orc = _orc_with_maya()
    orc.privacy.pause()                              # Veil down → nothing kept
    r = orc.handle_voice("remember Maya loves oat milk")
    assert r["ok"] is False
    assert orc.social._enricher.get_notes("maya") in (None, "")


# -- third-party introductions (professional / family) ------------------------

def test_intro_grammar_captures_relationship():
    from dreamlayer.social_lens.introduction import parse_introduction_ex
    assert parse_introduction_ex("this is my brother Dan") == ("Dan", "brother")
    assert parse_introduction_ex("meet my colleague Sarah") == ("Sarah", "colleague")
    assert parse_introduction_ex("have you met Tom") == ("Tom", None)
    # still a self-intro, and still refuses non-names
    assert parse_introduction_ex("I'm Maya") == ("Maya", None)
    assert parse_introduction_ex("this is my car") is None
    assert parse_introduction_ex("I'm running late") is None


def test_third_party_intro_creates_contact_with_relationship_note():
    fr = SocialLens()                               # empty — never met anyone
    card = fr.offer_introduction("this is my brother Dan", frame=_frame(0.8))
    assert card is not None and fr.contact_count == 1
    res = fr.identify(_frame(0.8))
    assert res.match.contact.name == "Dan"
    assert res.match.contact.relation == "brother"        # how you know them
    assert res.to_hud_card()["relation"] == "brother"     # led on the recall card


# -- meet someone on the spot -------------------------------------------------

def test_meet_person_grammar():
    it = parse_intent("Hey Juno, this is my colleague Sarah, she runs marketing")
    assert it.kind == "meet_person"
    assert it.args["who"] == "Sarah" and it.args["relation"] == "colleague"
    assert it.args["note"] == "she runs marketing"
    # "meet" and bare "this is Name"
    assert parse_intent("meet my brother Dan").args["who"] == "Dan"
    assert parse_intent("this is Tom").kind == "meet_person"


def test_orchestrator_meet_someone_new_then_recall_shows_dossier():
    orc = Orchestrator(FakeBridge())                # no contacts at all
    r = orc.handle_voice(
        "this is my colleague Sarah, she runs marketing", frame=_frame(0.8))
    assert r["ok"] is True and r["who"] == "Sarah"
    # created + recallable, dossier seeded with relation and note
    res = orc.look_at_person(_frame(0.8))
    assert res is not None and res["person"] == "Sarah"
    assert "runs marketing" in res["identity"]["note"]        # newest note shown
    assert res["identity"]["relation"] == "colleague"         # leads the card
    # the rescue cue combines it all
    cue = res["rescue"]
    assert cue["name"] == "Sarah" and cue["relation"] == "colleague"
    assert "runs marketing" in cue["note"]
    stored = orc.social._enricher.get_notes(res["identity"]["contact_id"])
    assert "runs marketing" in stored                         # note kept
    assert orc.social._enricher.get_relation(res["identity"]["contact_id"]) == "colleague"


def test_rescue_cue_leads_with_name_relation_lastseen_note():
    # you meet a colleague, note something, then chat — later a look gives you
    # everything you need to not blank: name, how you know them, last-seen, note
    orc = Orchestrator(FakeBridge())
    orc.handle_voice("this is my colleague Sarah, she runs marketing", frame=_frame(0.8))
    orc.ingest_caption("the Q3 deck is ready", speaker="Sarah")   # ledger knows her
    res = orc.look_at_person(_frame(0.8))
    cue = res["rescue"]
    assert cue["name"] == "Sarah"
    assert cue["relation"] == "colleague"
    assert "runs marketing" in cue["note"]
    assert cue["last_seen"]                       # "just now" / "Ns ago"
    # and the identity card itself leads with the relationship
    assert "colleague" in res["identity"]["lines"]


def test_orchestrator_meet_is_veil_gated():
    orc = Orchestrator(FakeBridge())
    orc.privacy.pause()
    r = orc.handle_voice("this is Sarah", frame=_frame(0.8))
    assert r["ok"] is False and orc.social.contact_count == 0


def test_meet_existing_contact_just_adds_the_note():
    orc = _orc_with_maya()
    before = orc.social.contact_count
    r = orc.handle_voice("this is Maya, she loves tea", frame=_frame(0.8))
    assert r["ok"] is True and orc.social.contact_count == before   # no dup
    assert "loves tea" in orc.social._enricher.get_notes("maya")
