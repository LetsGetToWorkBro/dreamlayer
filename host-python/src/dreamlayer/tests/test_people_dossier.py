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
    assert out["veiled"] is True
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
