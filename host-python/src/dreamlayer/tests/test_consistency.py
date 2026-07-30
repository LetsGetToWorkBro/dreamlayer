"""test_consistency.py — on-device fact consistency over your own memories."""
from __future__ import annotations

import pytest

from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent
from dreamlayer.orchestrator.consistency import ConsistencyEngine, contradicts

NOW = 1000.0


def ring_with(*mems) -> SemanticRingBuffer:
    """mems: (summary, confidence[, meta]) tuples."""
    ring = SemanticRingBuffer(capacity=64)
    for i, m in enumerate(mems):
        summary, conf = m[0], m[1]
        meta = m[2] if len(m) > 2 else {}
        ring.append(MemoryEvent(kind="memory", summary=summary,
                                confidence=conf, meta=meta), ts=NOW + i)
    return ring


class TestContradictions:
    def test_negation_flip(self):
        eng = ConsistencyEngine(ring_with(("the store is open on Sundays", 0.8)))
        r = eng.check("the store is not open on Sundays")
        assert r.fired and r.reason == "negation"
        assert "open on Sundays" in r.prior_summary

    def test_antonym_states(self):
        eng = ConsistencyEngine(ring_with(("the front door is open", 0.8)))
        r = eng.check("the front door is closed")
        assert r.fired and r.reason == "antonym"
        assert r.detail == "open vs closed"

    def test_value_conflict(self):
        eng = ConsistencyEngine(ring_with(("meeting with Sarah at 3", 0.8)))
        r = eng.check("meeting with Sarah at 4")
        assert r.fired and r.reason == "value"
        assert r.card["type"] == "ConsistencyCard"


class TestNoFalsePositives:
    def test_agreement_does_not_fire(self):
        eng = ConsistencyEngine(ring_with(("meeting with Sarah at 3", 0.8)))
        assert eng.check("meeting with Sarah at 3 is confirmed").fired is False

    def test_unrelated_subject_does_not_fire(self):
        eng = ConsistencyEngine(ring_with(("bought milk this morning", 0.8)))
        assert eng.check("the sky is blue today").fired is False

    def test_same_number_different_subject_does_not_fire(self):
        eng = ConsistencyEngine(ring_with(("bought 3 apples", 0.8)))
        assert eng.check("there are 3 cars outside").fired is False

    def test_value_needs_numbers_on_both_sides(self):
        eng = ConsistencyEngine(ring_with(("call Sarah tomorrow", 0.8)))
        # a number appears only in the new claim: no value contradiction
        assert eng.check("call Sarah at 5").fired is False

    def test_empty_baseline(self):
        assert ConsistencyEngine(ring_with()).check("anything at all").fired is False


class TestPrivacy:
    def test_private_memories_are_never_compared(self):
        eng = ConsistencyEngine(ring_with(
            ("dinner reservation at 7", 0.8, {"private": True})))
        assert eng.check("dinner reservation at 8").fired is False

    def test_low_confidence_priors_ignored(self):
        eng = ConsistencyEngine(ring_with(("the gate is open", 0.1)))
        assert eng.check("the gate is closed").fired is False


class TestCard:
    def test_card_shows_both_sides(self):
        eng = ConsistencyEngine(ring_with(("the store is open Sundays", 0.8)))
        card = eng.check("the store is not open Sundays").card
        assert card["primary"] == "the store is not open Sundays"
        assert card["footer"] == "the store is open Sundays"
        assert "different" in card["eyebrow"].lower()


# --------------------------------------------------------------------------
# The corpus. Candor shipped scoring 3 of these 9 true contradictions, which is
# why `FactCheckCard` was recorded as "blocked by an engine that misses real
# contradictions" rather than wired — a producer on top of a scorer that cannot
# see the case in its own docstring would have satisfied the reachability
# checker and blinded it.
#
# Both halves are load-bearing and the errors are NOT symmetric. A miss makes
# the lens quiet. A false fire pushes a card telling the wearer they
# contradicted themselves, quoting a sentence that was about something else.
# So MUST_NOT_FIRE is the half to grow when tuning, and it includes the case
# that regressed when the subject gate was first relaxed.
# --------------------------------------------------------------------------

MUST_FIRE = [
    # the module docstring's own example — "the meeting was at 3, now 4" —
    # written the way people say it. `\b\d{1,4}\b` cannot match the 3 in "3pm"
    # (the trailing \b gets `p`), so BOTH sides extracted no number at all.
    # THE headline case, and the one that stayed broken longest: two clock
    # times about one appointment share exactly one content word, because the
    # times ARE the disagreement and cannot also be the shared subject.
    ("the meeting is at 3pm", "the meeting is at 4pm", "value"),
    ("the lease renewal is at 3pm", "the lease renewal is at 4pm", "value"),
    ("I booked the table for 8pm", "I booked the table for 9pm", "value"),
    ("the standup moved to 10am", "the standup moved to 11am", "value"),
    # explicit negation, one shared noun. Digits are dropped from keywords, so
    # this shared exactly one and fell short of the gate of two — the clearest
    # possible contradiction, invisible.
    ("the meeting is at 3", "the meeting is not at 3", "negation"),
    # send/sent is not a suffix difference, so these shared only "invoice"
    ("I sent the invoice", "I did not send the invoice", "negation"),
    ("Ana is coming to dinner", "Ana is not coming to dinner", "negation"),
    ("the shop is open on sunday", "the shop is closed on sunday", "antonym"),
    ("Ana said the flat is free on friday",
     "Ana said the flat is busy on friday", "antonym"),
    ("rent is 1200 a month", "rent is 1400 a month", "value"),
]

MUST_NOT_FIRE = [
    # a line against itself, and against a longer version of itself
    ("I will send the invoice tomorrow", "I will send the invoice tomorrow"),
    ("call Ana about the lease", "call Ana about the lease"),
    ("I sent the invoice", "I sent the invoice yesterday"),
    ("the budget is 5000", "the budget is 5000"),
    # DIFFERENT NAMED SUBJECTS — the regression the named-subject check exists
    # for. Shares "coming" and "dinner", clears the gate, trips the negator
    # asymmetry, and is two people rather than one contradiction.
    ("Ana is coming to dinner", "Bob is not coming to dinner"),
    ("Ana flight is at 3pm", "Bob flight is at 4pm"),
    # a shared number is not a shared subject
    ("the meeting is at 3", "the invoice is not 3 pages"),
    ("rent is 1200 a month", "the flight was 1400 euros"),
    ("the shop is open", "the library is closed"),
    # A TIME and a DURATION are two different measurements, both true. Without
    # the same-kind check the comparable-values rule fires here on one shared
    # word — the false accusation that rule could most easily have caused.
    ("the meeting is at 3pm", "the meeting ran 4 hours"),
    ("the meeting is at 3pm", "the invoice was 4000"),
]


@pytest.mark.parametrize("claim,prior,reason", MUST_FIRE)
def test_a_real_contradiction_is_seen(claim, prior, reason):
    got = contradicts(claim, prior)
    assert got is not None, f"missed: {claim!r} vs {prior!r}"
    assert got[0] == reason, got


@pytest.mark.parametrize("claim,prior", MUST_NOT_FIRE)
def test_an_unrelated_pair_is_left_alone(claim, prior):
    assert contradicts(claim, prior) is None, (
        f"false accusation: {claim!r} vs {prior!r}")


def test_the_corpus_is_symmetric_where_it_should_be():
    """Order must not decide the verdict — Candor compares a new line against
    every earlier one, and which is "claim" is an accident of arrival."""
    for claim, prior, _reason in MUST_FIRE:
        assert contradicts(prior, claim) is not None, (claim, prior)
    for claim, prior in MUST_NOT_FIRE:
        assert contradicts(claim, prior) is None, (claim, prior)


def test_clock_times_survive_the_number_scan():
    """The regex change, isolated. Both forms must be extracted, and a bare
    hour must not be pulled out of a clock time as a separate number."""
    from dreamlayer.orchestrator.consistency import _NUM
    assert _NUM.findall("the lease is at 3pm") == ["3pm"]
    assert _NUM.findall("moved to 10 am") == ["10 am"]
    assert _NUM.findall("call at 3:30pm sharp") == ["3:30pm"]
    assert _NUM.findall("rent is 1200") == ["1200"]


def test_normalisation_is_narrow_on_purpose():
    """A general stemmer would collapse unrelated words and turn misses into
    false accusations. These are the folds it may make, and one it may not."""
    from dreamlayer.orchestrator.consistency import _norm
    assert _norm("sent") == "send"
    assert _norm("booked") == "book"
    assert _norm("invoices") == "invoice"
    assert _norm("lease") != _norm("least")     # not a suffix relationship


def test_the_number_bonuses_do_not_stack():
    """A regression the corpus caught. Two lines sharing NO content word but
    quoting the same "3" collected a point for "same value" AND a point for
    "same kind of value" — over one identical number — reaching the threshold
    and firing a negation on two unrelated sentences. At most one point."""
    assert contradicts("the meeting is at 3", "the invoice is not 3 pages") is None
