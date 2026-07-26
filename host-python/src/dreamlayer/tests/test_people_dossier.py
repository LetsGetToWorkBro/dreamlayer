"""The people dossier + the ambient-push self-test — the two halves of the HUD
that the 2026-07-23 demo-readiness audit found unreachable on the shipped Brain.

The dossier is NAME-keyed on purpose. The Brain the phone talks to has no
face-recognition model (truth_lens.face_embed is a documented deterministic stub:
it reports a face in any non-dark frame and hashes pixel sums, so two photos of
one person never match). These pin the honest contract:

  * a dossier is built ONLY from your own records, for someone you introduced,
  * a general question is NEVER hijacked into a person lookup,
  * a person you never introduced is never guessed at,
  * a self-test card announces itself and never borrows a safety alert's
    privilege to pierce the veil.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain():
    b = Brain(tempfile.mkdtemp())
    b.introduce("this is Sarah Chen from Acme")
    b.add_person("Marcus", note="climbing partner")
    return b


# --- the dossier -------------------------------------------------------------

def test_a_person_you_introduced_comes_back_as_a_real_card(brain):
    d = brain.dossier_query("who is Sarah")
    assert d is not None
    card = d["card"]
    assert card["type"] == "PersonDossierCard"
    assert card["person"] == "Sarah Chen"           # bare first name resolves
    assert d["say"]                                  # a spoken line too


def test_the_dossier_carries_only_your_own_records(brain):
    d = brain.person_dossier("Marcus")
    assert d["known"] is True
    # the note you gave at introduction is the substance — nothing invented
    assert "climbing partner" in d["notes"]
    assert d["card"]["footer"] == "climbing partner"


def test_a_general_question_is_not_hijacked_into_a_person_lookup(brain):
    # the dossier is roster-gated: these must fall through to normal recall
    assert brain.dossier_query("who is the mayor of Boston") is None
    assert brain.dossier_query("who is the president") is None
    assert brain.dossier_query("who was the first person on the moon") is None


def test_a_non_question_is_not_a_dossier_query(brain):
    assert brain.dossier_query("where did I leave my keys") is None
    assert brain.dossier_query("") is None
    assert brain.dossier_query("Sarah") is None      # a name alone isn't a question


def test_someone_you_never_introduced_is_never_guessed_at(brain):
    assert brain.dossier_query("who is Jane") is None
    d = brain.person_dossier("Jane")
    assert d == {"known": False, "name": "Jane"}


def test_an_ambiguous_first_name_is_never_guessed_between_two_people(brain):
    brain.add_person("Sarah Okafor", note="from the climbing gym")
    # two Sarahs → a bare "Sarah" must NOT resolve to either one
    assert brain.dossier_query("who is Sarah") is None
    # the full name still resolves
    assert brain.dossier_query("who is Sarah Okafor")["who"] == "Sarah Okafor"


def test_a_name_that_is_also_an_ordinary_word_cannot_hijack_a_question(brain):
    """Will / May / Art / Grace are names AND words. The dossier only fires when
    the name is the OBJECT of the question, so a general question falls through
    to normal recall."""
    brain.add_person("Will", note="my brother")
    brain.add_person("May", note="neighbour")
    assert brain.dossier_query("who is the will of the people") is None
    assert brain.dossier_query("tell me about the will I signed") is None
    assert brain.dossier_query("tell me about the may flowers") is None
    # the real question still works
    assert brain.dossier_query("who is Will")["who"] == "Will"
    assert brain.dossier_query("what do I know about May")["who"] == "May"


def test_a_possessive_question_is_about_someone_else(brain):
    # "who is Sarah's manager" asks about the manager — not Sarah's own dossier
    assert brain.dossier_query("who is Sarah Chen's manager") is None


def test_a_different_surname_is_never_answered_as_the_person_you_know(brain):
    """Roster holds Sarah Chen; asking about a different Sarah must not return her."""
    assert brain.dossier_query("who is Sarah Okafor") is None
    assert brain.dossier_query("who is Sarah Chen")["who"] == "Sarah Chen"


def test_hostile_input_never_raises(brain):
    brain.add_person("a.*b")                      # regex metacharacters as a name
    for q in (None, "", "   ", "who is " + "x" * 10_000, "who is a.*b", "who is ("):
        brain.dossier_query(q)                    # must not raise
    for n in (None, "", "   ", 12345, "a.*b"):
        assert isinstance(brain.person_dossier(n), dict)


def test_the_dossier_never_runs_face_recognition(brain):
    """The trigger is a name, never a frame — the guard against re-wiring the
    stub embedder into an identity claim."""
    import inspect
    src = inspect.getsource(type(brain).person_dossier)
    for banned in ("face_embed", "FaceEmbedder", "identify", "embedding"):
        assert banned not in src


# --- the 2026-07-23 security/privacy refute-audit findings -------------------

def test_an_unrelated_private_note_is_never_surfaced_as_a_mention(tmp_path):
    """HIGH: the index matches on ANY shared keyword, so an unfiltered lookup
    turned roster 'Bill' into 'Electric bill ... card ending 4412', captioned as
    being about Bill. A mention must NAME them, case-sensitively."""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.txt").write_text("Electric bill 340 dollars paid with card ending 4412\n")
    (notes / "b.txt").write_text("Bill said he would bring the ladder on Saturday\n")
    b = Brain(str(tmp_path))
    b.config.folders = [str(notes)]
    b.index.reindex()
    b.add_person("Bill", note="neighbour")
    d = b.person_dossier("Bill")
    assert not any("4412" in m for m in d["mentions"])
    assert any("ladder" in m for m in d["mentions"])
    # the caption is your own note, never a keyword-matched passage
    assert d["card"]["footer"] == "neighbour"


def test_the_veil_stops_the_brain_recording_who_you_asked_about(brain):
    brain.config.network_mode = "lan_only"           # incognito
    before = len(brain.activity.recent(50))
    assert brain.dossier_query("who is Sarah")["who"] == "Sarah Chen"
    assert len(brain.activity.recent(50)) == before   # nothing written


def test_a_real_safety_card_survives_a_queue_full_of_ambient_events(brain):
    """A stalled reader is exactly when a smoke alarm matters most, and the queue
    drops the NEWEST event — so a burst of ambient cards could bury it."""
    q = brain.subscribe_events()
    for i in range(q.maxsize):
        q.put_nowait({"kind": "ambient", "safety": False, "n": i})
    assert brain.push_event("hark", {"type": "HarkCard"}, veil_ok=True) == 1
    items = [q.get_nowait() for _ in range(q.qsize())]
    assert any(i.get("safety") for i in items)       # the alarm got through
    assert not any(i.get("n") == 0 for i in items)   # the oldest ambient made room


def test_the_selftest_is_rate_limited(brain):
    brain.subscribe_events()
    oks = [brain.push_selftest("hark").get("ok") for _ in range(brain.MAX_SELFTEST_PER_MIN + 2)]
    assert oks.count(True) == brain.MAX_SELFTEST_PER_MIN
    assert oks[-1] is False


def test_the_selftest_marker_survives_the_device_card_path(brain):
    """The glasses' own renderers hard-code the eyebrow and drop unknown fields,
    so the marker has to ride the fields they DO render — and a test must not
    borrow a real tap's earcon/haptic/flash."""
    q = brain.subscribe_events()
    brain.push_selftest("hark")
    card = q.get_nowait()["card"]
    assert card["lines"][0] == "SELF-TEST"
    assert not any(k in card for k in ("earcon", "haptic", "flash"))


def test_a_large_roster_does_not_make_a_question_expensive(brain):
    """Cost is O(question), not O(roster): sync_contacts can put an entire address
    book in people.json, and the old per-name regex loop also evicted Python's
    global re cache."""
    import re as _re
    import time as _time
    for i in range(400):
        brain.add_person(f"Person{i} Sur{i}")
    _re._cache.clear()
    t0 = _time.perf_counter()
    for _ in range(20):
        brain.dossier_query("who is Sarah Chen")
    assert (_time.perf_counter() - t0) / 20 < 0.05    # was ~52 ms at N=800
    assert len(_re._cache) < 64                       # no global cache thrash


def test_a_trailing_punctuation_name_is_reachable(brain):
    brain.add_person("Smith Jr.", note="the elder")
    assert brain.dossier_query("who is Smith Jr.")["who"] == "Smith Jr."


def test_a_lowercase_roster_name_still_cannot_surface_a_private_note(tmp_path):
    """The case-sensitivity guard was useless for a lowercase roster entry —
    add_person/sync_contacts store the name verbatim (audit 3, HIGH)."""
    notes = tmp_path / "n"
    notes.mkdir()
    (notes / "a.txt").write_text("Electric bill 340 dollars paid with card ending 4412\n")
    b = Brain(str(tmp_path))
    b.config.folders = [str(notes)]
    b.index.reindex()
    b.add_person("bill")                              # lowercase, not "Bill"
    assert b.person_dossier("bill")["mentions"] == []


def test_a_mention_is_never_another_person_with_the_same_first_name(tmp_path):
    """Probing a bare first name attributed Sarah Okafor's debt to Sarah Chen
    (audit 3, HIGH)."""
    notes = tmp_path / "n"
    notes.mkdir()
    (notes / "a.txt").write_text(
        "Sarah Chen signed the Q3 renewal.\n"
        "Sarah Okafor owes me 200 dollars from the trip.\n")
    b = Brain(str(tmp_path))
    b.config.folders = [str(notes)]
    b.index.reindex()
    b.add_person("Sarah Chen")
    m = b.person_dossier("Sarah Chen")["mentions"]
    assert any("Q3 renewal" in x for x in m)
    assert not any("Okafor" in x for x in m)


def test_an_unvalidated_phone_mirror_cannot_break_the_dossier(brain):
    """receive_people stores the phone's payload unvalidated; a bad row used to
    raise and kill People lookups for everyone (audit 3)."""
    brain.add_person("Zed")
    brain.social_people = [None, {"name": None}, "junk",
                           {"name": "Zed", "notes": ["real note"], "debts": 7}]
    d = brain.person_dossier("Zed")
    assert d["known"] is True
    assert d["notes"] == ["real note"]                 # the string/int rows ignored
    assert d["debts"] == []
    brain.social_people = [{"name": "Zed", "notes": "hello"}]
    assert brain.person_dossier("Zed")["notes"] == []  # never char-split


def test_a_typographic_apostrophe_matches_a_straight_one(brain):
    """Contacts stores ’ while a typed ' is common — they must be the same name."""
    brain.add_person("O'Brien", note="the landlord")
    assert brain.dossier_query("who is O’Brien")["who"] == "O'Brien"


def test_a_non_string_query_never_raises(brain):
    for q in (12345, 3.14, True, ["x"], None):
        brain.dossier_query(q)


# --- the ambient-push self-test ---------------------------------------------

def test_every_selftest_kind_pushes_a_card_that_announces_itself(brain):
    q = brain.subscribe_events()
    for kind in brain.SELFTEST_KINDS:
        assert brain.push_selftest(kind)["delivered"] == 1
        card = q.get_nowait()["card"]
        assert card["selftest"] is True
        assert card["eyebrow"] == "SELF-TEST"
        assert "elf-test" in str(card.get("primary") or card.get("text") or "")


def test_a_selftest_never_pierces_the_veil(brain):
    """A real smoke alarm pierces the shield; a self-test must never borrow that
    privilege — and being suppressed is itself proof the shield works."""
    brain.config.network_mode = "lan_only"           # incognito
    q = brain.subscribe_events()
    out = brain.push_selftest("hark")
    assert out["delivered"] == 0
    assert out["reason"] == "veiled"      # says WHY, not just "0 delivered"
    assert q.empty()


def test_an_unknown_selftest_kind_is_refused(brain):
    q = brain.subscribe_events()
    out = brain.push_selftest("spoof-a-real-alarm")
    assert out["ok"] is False
    assert q.empty()                                  # nothing was pushed


def test_the_hark_selftest_is_not_dressed_as_a_real_alert(brain):
    q = brain.subscribe_events()
    brain.push_selftest("hark")
    card = q.get_nowait()["card"]
    # a real watch-out is "urgent"; a test tone must not claim that weight
    assert card.get("importance") != "urgent"
    assert "not a real alert" in str(card.get("detail", ""))
