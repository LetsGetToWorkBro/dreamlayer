"""The answer before you speak — `AnswerAheadCard`.

Recorded as blocked on "a predicted question the premonition lens does not
produce". That was a mis-read of the TITLE: `answer_ahead`'s own docstring is
"a question the room just asked you, with the answer already pulled from your
knowledge", and its signature is `(question, answer, speaker, source)`. Nothing
needs predicting — the question arrives in the transcript. Fourth card in this
audit whose blocker turned out to be my reading of its name.

The pieces all shipped already: the ear transcribes, `detect_claim`'s inverse
finds questions, `brain.ask` answers from the wearer's own memory, `push_event`
draws. What needed care was the gating, and the tests below are mostly about
that rather than about the happy path.

The sharpest one is `no_cloud`. A wearer typing a question chose to ask it and
may egress; a bystander's overheard sentence chose nothing, so it must never
leave the device — whatever the cloud settings say.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.schema import Answer
from dreamlayer.ai_brain.server.ear import EarHost
from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain():
    b = Brain(tempfile.mkdtemp())
    b.config.answer_ahead_enabled = True
    return b


def _pushes(brain):
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card)) or 1)
    return seen


def _answers(brain, text="the lease was signed in March", conf=0.8, tier="laptop"):
    calls = []

    def _ask(query, no_cloud=False):
        calls.append({"query": query, "no_cloud": no_cloud})
        return Answer(text=text, sources=[], tier=tier, confidence=conf)
    brain.ask = _ask
    return calls


# --- the gate that matters --------------------------------------------------

def test_an_overheard_question_never_reaches_the_cloud(brain):
    """The whole reason this is safe to wire. `no_cloud=True` is passed as a
    CONSTANT, not read from config, so no setting can turn it off."""
    ear = EarHost(brain)
    calls = _answers(brain)
    _pushes(brain)
    ear.ingest_caption("when did we sign the lease on the flat?")
    assert calls and calls[0]["no_cloud"] is True


def test_the_no_cloud_flag_is_not_configurable(brain):
    """A source assertion, because a behavioural test cannot tell a hard-coded
    True from a config value that happens to be True in the fixture."""
    import inspect
    src = inspect.getsource(EarHost._answer_ahead)
    body = src.split('"""')[-1]
    assert "no_cloud=True" in body
    for banned in ("cloud_enabled", "cloud_ready", "no_cloud=self", "no_cloud=g"):
        assert banned not in body, f"the on-device guarantee became configurable: {banned}"


# --- it works ---------------------------------------------------------------

def test_a_question_the_brain_knows_is_answered_on_the_glass(brain):
    ear = EarHost(brain)
    _answers(brain)
    seen = _pushes(brain)
    ear.ingest_caption("when did we sign the lease on the flat?")
    kind, card = seen[-1]
    assert kind == "answer_ahead" and card["type"] == "AnswerAheadCard"
    assert "March" in card["primary"]            # the answer leads
    assert "lease" in card["detail"]             # the question rides under it
    assert card["footer"] == "laptop"            # provenance, not a bare fact


def test_the_speaker_is_never_attributed(brain):
    """Nothing populates `speaker`, and inventing one would mean voiceprinting
    everyone in earshot — the limit `ear.py` already states."""
    ear = EarHost(brain)
    _answers(brain)
    seen = _pushes(brain)
    ear.ingest_caption("what time does the shop close on sunday?")
    # the builder folds speaker into `footer` as "<speaker> · <source>", so an
    # empty speaker means the footer is the provenance alone
    assert seen[-1][1]["footer"] == "laptop"
    import inspect
    body = inspect.getsource(EarHost._answer_ahead).split('"""')[-1]
    assert 'speaker=""' in body, "an attribution crept into the answer card"


# --- the gates ---------------------------------------------------------------

def test_it_is_off_by_default(brain):
    brain.config.answer_ahead_enabled = False
    ear = EarHost(brain)
    calls = _answers(brain)
    seen = _pushes(brain)
    ear.ingest_caption("when did we sign the lease on the flat?")
    assert calls == [] and seen == []
    assert ear.heard_count == 1                  # …but it still remembered it


def test_a_statement_is_not_a_question(brain):
    ear = EarHost(brain)
    calls = _answers(brain)
    ear.ingest_caption("the lease was signed in March and we moved in April")
    assert calls == []


@pytest.mark.parametrize("line", ["what?", "really?", "huh?", "and?"])
def test_a_bare_interjection_is_not_a_question(brain, line):
    """Every false positive spends a memory search and risks a card the wearer
    cannot un-see. Four words minimum."""
    ear = EarHost(brain)
    calls = _answers(brain)
    ear.ingest_caption(line)
    assert calls == [], line


def test_a_question_without_punctuation_still_counts(brain):
    """ASR punctuation is unreliable and a transcript often arrives with none,
    so an interrogative opener has to qualify on its own."""
    ear = EarHost(brain)
    calls = _answers(brain)
    ear.ingest_caption("when did we sign that lease")
    assert len(calls) == 1


def test_a_weak_answer_stays_quiet(brain):
    """`ask` falls through tiers and returns a keyword-index hit for almost
    anything. Drawing that puts a confident-looking wrong answer on the glass
    in the middle of a conversation."""
    ear = EarHost(brain)
    _answers(brain, conf=0.2)
    seen = _pushes(brain)
    ear.ingest_caption("when did we sign the lease on the flat?")
    assert seen == []


def test_an_empty_answer_draws_nothing(brain):
    ear = EarHost(brain)
    _answers(brain, text="   ")
    seen = _pushes(brain)
    ear.ingest_caption("when did we sign the lease on the flat?")
    assert seen == []


def test_a_conversation_is_not_answered_continuously(brain):
    """A conversation is mostly questions. Without the gap the glass would
    answer every one of them, which is useless and the fastest way to make a
    wearer switch the feature off."""
    ear = EarHost(brain)
    _answers(brain)
    seen = _pushes(brain)
    for _ in range(5):
        ear.ingest_caption("when did we sign the lease on the flat?")
    assert len(seen) == 1


def test_the_veil_answers_nothing(brain):
    """Incognito drops the utterance before anything downstream sees it."""
    ear = EarHost(brain)
    brain.config.network_mode = "lan_only"
    calls = _answers(brain)
    seen = _pushes(brain)
    ear.ingest_caption("when did we sign the lease on the flat?")
    assert calls == [] and seen == []
    assert ear.heard_count == 0


def test_a_raising_brain_never_costs_the_memory(brain):
    """A card is never worth an utterance."""
    ear = EarHost(brain)

    def _boom(*a, **k):
        raise RuntimeError("no model")
    brain.ask = _boom
    ear.ingest_caption("when did we sign the lease on the flat?")
    assert ear.heard_count == 1


def test_the_question_asked_is_the_redacted_one(brain):
    """The lookup runs AFTER the PII scrub, so an identifier in an overheard
    question is never used as a search key."""
    pytest.importorskip("presidio_analyzer")
    ear = EarHost(brain)
    calls = _answers(brain)
    ear.ingest_caption("did you call 555-123-4567 about the lease")
    assert calls and "555-123-4567" not in calls[0]["query"]


def test_the_switch_is_reachable(brain):
    """A config field outside `apply_config`'s allowlist is settable by nothing
    — a panel switch that silently does nothing."""
    brain.apply_config({"answer_ahead_enabled": True})
    assert brain.config.answer_ahead_enabled is True
    assert brain.config.public()["answer_ahead_enabled"] is True


def test_it_is_its_own_switch(brain):
    """Turning Listening or captions on must not turn this on."""
    b = Brain(tempfile.mkdtemp())
    b.apply_config({"listen_enabled": True, "captions_enabled": True})
    assert b.config.answer_ahead_enabled is False
