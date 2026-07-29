"""Truth Lens, reframed — what THEY said, last time.

The nine-stage gauge inferred DECEPTION from a bystander's face and voice. That
was rejected on three grounds, and the third is the one that decided it: the
inference has no reliable basis, and the stages that would lend it credibility
(`au_detector.process`, `face_embed`, every class in `au_backends`) are
documented no-ops, so it would have rendered a keyword heuristic as a
nine-ring biometric readout.

This answers a question that IS answerable and wholly verifiable: what did this
person tell you before, and does it square with what they just said? Both sides
are quotes. Nothing is inferred about anyone's interior; no biometric is
computed at all; and the wearer judges, because both statements are on the card.

The load-bearing constraint is ATTRIBUTION. Everything here depends on knowing
who said something, and this product deliberately cannot infer that — so it is
supplied by the wearer and refused when absent. A baseline that is not really
theirs produces a false contradiction against a named individual, which is the
one outcome that would make this worse than the thing it replaces.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _pushes(brain):
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card)) or 1)
    return seen


# --- attribution is never guessed -------------------------------------------

class TestAttributionIsNeverGuessed:

    def test_an_unattributed_claim_is_refused_not_resolved(self, brain):
        """The whole integrity of the feature. Nothing does diarization, so an
        unnamed speaker cannot be matched against anyone's history — and the
        honest answer is to refuse rather than to pick the likeliest person."""
        ls = brain.lenses()
        ls.ingest_utterance("the deposit is 1200", via="heard", said_by="Ana")
        out = ls.they_said("", "the deposit is 1400")
        assert out["fired"] is False
        assert out["reason"] == "no-attribution"

    def test_one_persons_words_are_never_matched_against_anothers(self, brain):
        """Ana said 1200; Bob now says 1400. That is two people quoting
        different numbers, not Bob contradicting himself."""
        ls = brain.lenses()
        ls.ingest_utterance("the deposit is 1200 a month", via="heard", said_by="Ana")
        seen = _pushes(brain)
        out = ls.they_said("Bob", "the deposit is 1400 a month")
        assert out["fired"] is False
        assert seen == []

    def test_the_speaker_key_is_not_the_promise_recipient(self, brain):
        """`meta["person"]` means the RECIPIENT on an extracted promise ("Promise
        to Ana: …"). Keying attribution on it would file a promise Ana made to
        Bob as something BOB said — an attribution the wearer would act on."""
        ls = brain.lenses()
        ls.ingest_utterance("I will send Ana the invoice on Friday",
                            via="heard", said_by="Marcus")
        marcus = ls.their_word("Marcus")
        ana = ls.their_word("Ana")
        assert marcus["promised"], "the promise lost its speaker"
        assert not ana["said"] and not ana["promised"], (
            "the promise recipient was recorded as its speaker")


# --- it answers ---------------------------------------------------------------

class TestWhatTheySaidLastTime:

    def test_a_changed_number_is_caught_and_both_sides_are_shown(self, brain):
        ls = brain.lenses()
        ls.ingest_utterance("the deposit is 1200 a month", via="heard", said_by="Ana")
        seen = _pushes(brain)
        out = ls.they_said("Ana", "the deposit is 1400 a month")
        assert out["fired"] is True and out["reason"] == "value"
        assert out["prior"] == "the deposit is 1200 a month"
        kind, card = seen[-1]
        assert kind == "they_said" and card["type"] == "DeviationAlertCard"
        # BOTH quotes ride the card — the evidence is the point
        assert "1400" in card["new_summary"]
        assert "1200" in card["prior_summary"]

    def test_a_flat_contradiction_is_caught(self, brain):
        ls = brain.lenses()
        ls.ingest_utterance("the survey is booked for Tuesday",
                            via="heard", said_by="Ana")
        out = ls.they_said("Ana", "the survey is not booked for Tuesday")
        assert out["fired"] is True and out["reason"] == "negation"

    def test_agreement_is_silence(self, brain):
        ls = brain.lenses()
        ls.ingest_utterance("the deposit is 1200 a month", via="heard", said_by="Ana")
        seen = _pushes(brain)
        out = ls.they_said("Ana", "the deposit is 1200 a month, as agreed")
        assert out["fired"] is False and seen == []

    def test_a_person_who_has_told_you_nothing_is_not_an_error(self, brain):
        ls = brain.lenses()
        out = ls.they_said("Ana", "the deposit is 1400")
        assert out["fired"] is False and out["checked"] == 0

    def test_matching_is_case_insensitive(self, brain):
        ls = brain.lenses()
        ls.ingest_utterance("the deposit is 1200 a month", via="heard", said_by="ana")
        assert ls.they_said("Ana", "the deposit is 1400 a month")["fired"] is True

    def test_the_veil_answers_nothing(self, brain):
        ls = brain.lenses()
        ls.ingest_utterance("the deposit is 1200 a month", via="heard", said_by="Ana")
        brain.config.network_mode = "lan_only"
        seen = _pushes(brain)
        out = ls.they_said("Ana", "the deposit is 1400 a month")
        assert out["fired"] is False and out["reason"] == "veiled"
        assert seen == []


# --- no verdict, ever ---------------------------------------------------------

class TestItMakesNoClaimAboutHonesty:

    def test_the_card_carries_no_deception_score(self, brain):
        """The line this feature exists on the right side of. A disagreement is
        reported; a judgement about the person is not."""
        ls = brain.lenses()
        ls.ingest_utterance("the deposit is 1200 a month", via="heard", said_by="Ana")
        seen = _pushes(brain)
        ls.they_said("Ana", "the deposit is 1400 a month")
        card = seen[-1][1]
        for banned in ("deception_prob", "verdict", "truthful", "deceptive",
                       "credibility", "stages"):
            assert banned not in card, f"a verdict crept onto the card: {banned}"

    def test_the_score_is_a_category_not_a_probability(self, brain):
        """`contradicts` returns a KIND of disagreement. The card's dot encodes
        which kind; deriving a percentage from a category is precisely the
        dressed-up-heuristic move the gauge was rejected for."""
        from dreamlayer.ai_brain.server.lens_hosts import BrainLenses
        ranks = set(BrainLenses._DISAGREEMENT_RANK)
        assert ranks == {"negation", "antonym", "value"}

    def test_no_biometric_is_computed(self, brain):
        """No face, no action units, no prosody. Source-asserted because this is
        the property that makes the feature acceptable at all."""
        import inspect
        from dreamlayer.ai_brain.server.lens_hosts import BrainLenses
        # CODE only — the docstring names the rejected stages in order to
        # explain what this replaces, so a naive substring search finds every
        # word it is asserting the absence of.
        body = inspect.getsource(BrainLenses.they_said).split('"""')[-1]
        code = "\n".join(ln.split("#")[0] for ln in body.splitlines())
        for banned in ("truth_lens", "face_embed", "au_detector", "prosody",
                       "AUFrame", "analyzer"):
            assert banned not in code, f"a biometric stage crept in: {banned}"


# --- what they promised -------------------------------------------------------

class TestWhatTheyPromised:

    def test_their_promises_are_tracked_separately_from_yours(self, brain):
        """What you owe and what you are owed are opposite ledgers. Merging them
        would put someone else's promise into your own commitment list."""
        ls = brain.lenses()
        ls.ingest_utterance("I will send you the invoice on Friday",
                            via="heard", said_by="Ana")
        theirs = ls.their_word("Ana")
        assert theirs["promised"], "their promise was not recorded"
        mine = [i["subject"] for i in ls.owed(push=False)["items"]]
        assert not any("invoice" in s for s in mine), (
            "someone else's promise landed in your own ledger")

    def test_a_promise_carries_whatever_due_date_it_has(self, brain):
        """The `due` plumbing, proven directly — because `extract_events` does
        NOT parse one out of "call you back in 2 h" (its `due` comes back empty
        for every phrasing tried), so driving this through the ear would assert
        a pipeline gap rather than this code. Recorded rather than worked
        around: their promises will show no deadline until the extractor learns
        to read one."""
        from dreamlayer.pipelines.ingest import MemoryEvent
        ls = brain.lenses()
        ls.ring.append(MemoryEvent(kind="promise", summary="Promise: call you back",
                                   confidence=0.85,
                                   meta={"said_by": "Ana", "due": "2h"}))
        rows = ls.their_word("Ana")["promised"]
        assert rows and rows[0]["due"], rows

    def test_the_extractor_gap_is_recorded_not_imagined(self):
        """Pins the limitation above, so it is noticed if it ever closes."""
        from dreamlayer.pipelines.ingest import extract_events
        promises = [e for e in extract_events("I will call you back in 2 h")
                    if e.kind == "promise"]
        assert promises, "the promise itself must still be extracted"
        assert not (promises[0].meta or {}).get("due"), (
            "extract_events learned to parse a due date — tighten the test above")

    def test_plain_talk_is_not_a_promise(self, brain):
        ls = brain.lenses()
        ls.ingest_utterance("the weather has been awful all week",
                            via="heard", said_by="Ana")
        theirs = ls.their_word("Ana")
        assert theirs["said"] and not theirs["promised"]

    def test_an_unnamed_speaker_has_no_ledger(self, brain):
        ls = brain.lenses()
        out = ls.their_word("")
        assert out["said"] == [] and out["reason"] == "no-attribution"

    def test_the_routes_reach_both(self, brain):
        from dreamlayer.ai_brain.server import server as srv
        text = open(srv.__file__, encoding="utf-8").read()
        assert '"/dreamlayer/theysaid": _get_they_said,' in text
        assert '"/dreamlayer/their": _get_their_word,' in text
