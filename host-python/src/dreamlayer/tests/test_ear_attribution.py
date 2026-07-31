"""Who SAID it versus who it is ABOUT — the ear's attribution key.

`ingest_utterance(text, *, via, person="", said_by="")` carries two different
facts and the ear was filling the wrong one. `person` is the SUBJECT of an
extracted event — who a promise is made to — while `said_by` is who uttered the
line. The ear passed its `speaker` as `person`.

Two things break on that, and both are the kind that look fine until they matter:

  * `owed()` returns the WEARER'S OWN commitments by excluding every row carrying
    `said_by`. A speaker in the `person` slot leaves an overheard promise looking
    like one the wearer made — someone else's debt on your list of debts.
  * `they_said` / `their_word` match on `said_by` alone, so "what did Marcus say
    last time" could never answer from live capture. That is the entire memory
    -based Truth Lens.

LATENT, NOT HARMLESS. `speaker` is empty on a shipped Brain today — no
CapturePipeline is built with a resolver — so nothing misbehaves yet. It bites the
moment any speaker producer is wired, which is the obvious next step here. These
tests pin the contract ahead of that producer rather than after it, and they pass a
speaker in explicitly because that is the future the fix exists for.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.ear import EarHost
from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain():
    b = Brain(tempfile.mkdtemp())
    b.config.listen_enabled = True
    return b


def _ring(brain):
    return brain.lenses().ring


def _metas(brain, kind=None):
    return [dict(b.event.meta or {})
            for b in _ring(brain).latest(kind=kind, limit=50)]


class TestTheAttributionKey:

    def test_the_speaker_lands_in_said_by(self, brain):
        EarHost(brain).ingest_caption("the deposit is paid on Friday",
                                      speaker="Marcus")
        heard = _metas(brain, "heard")
        assert heard, "nothing reached the ring"
        assert heard[0].get("said_by") == "Marcus"

    def test_the_speaker_does_NOT_land_in_person(self, brain):
        """`person` is who the statement is ABOUT. Putting the speaker there is
        the overloading `said_by` was introduced to end."""
        EarHost(brain).ingest_caption("the deposit is paid on Friday",
                                      speaker="Marcus")
        assert not _metas(brain, "heard")[0].get("person")

    def test_an_unattributed_utterance_carries_no_speaker(self, brain):
        """The state every shipped Brain is in today. An empty speaker must leave
        `said_by` unset rather than storing "" as an attribution."""
        EarHost(brain).ingest_caption("the deposit is paid on Friday")
        assert not str(_metas(brain, "heard")[0].get("said_by") or "").strip()


class TestTheLedgerStaysTheWearersOwn:

    def test_an_overheard_promise_does_not_join_your_own_debts(self, brain):
        """The failure this fix prevents. `owed()` is what you owe; a promise
        someone else made out loud is the opposite ledger."""
        EarHost(brain).ingest_caption("I'll send you the lease tomorrow",
                                      speaker="Marcus")
        owed = brain.lenses().owed()
        for row in owed["items"]:
            assert "lease" not in str(row).lower(), row

    def test_your_own_utterance_still_reaches_your_ledger(self, brain):
        """The other direction, so the fix cannot be "nothing is ever owed".
        With no speaker the line is the wearer's own and must still count."""
        EarHost(brain).ingest_caption("I'll send you the lease tomorrow")
        rows = brain.lenses().owed()["items"]
        assert rows, "the wearer's own promise vanished from their ledger"

    def test_the_two_ledgers_do_not_overlap(self, brain):
        """One utterance each way; neither may appear in the other's list."""
        ear = EarHost(brain)
        ear.ingest_caption("I'll send you the lease tomorrow")          # wearer
        ear.ingest_caption("I'll get the survey done by Friday",
                           speaker="Marcus")                            # theirs
        mine = " ".join(str(r) for r in brain.lenses().owed()["items"]).lower()
        assert "lease" in mine
        assert "survey" not in mine, "their promise landed in your ledger"


class TestTheMemoryTruthLensCanFinallyAnswer:

    def test_what_someone_said_is_recallable_by_name(self, brain):
        """`their_word` matches on `said_by` alone. With the speaker in the wrong
        key it returned nothing no matter how much was heard — the memory-based
        Truth Lens had no live input at all."""
        EarHost(brain).ingest_caption("the roof was replaced last year",
                                      speaker="Marcus")
        said = brain.lenses().their_word("Marcus").get("said") or []
        assert any("roof" in str(r.get("summary", "")).lower() for r in said), said

    def test_it_does_not_answer_for_someone_who_said_nothing(self, brain):
        EarHost(brain).ingest_caption("the roof was replaced last year",
                                      speaker="Marcus")
        assert not (brain.lenses().their_word("Priya").get("said") or [])

    def test_their_word_tracks_a_named_persons_promise(self, brain):
        """"Keep track of promises people make" — the ask this whole path serves.

        `their_word` splits `said` from `promised`, which is the right shape for
        the question: what someone told you and what they committed to are
        different things to hold them to. The EXTRACTED promise row has to carry
        the attribution too, not just the raw line it came from — they are two
        separate `observe` calls and only one of them is obvious.
        """
        EarHost(brain).ingest_caption("I will get the survey done by Friday",
                                      speaker="Marcus")
        out = brain.lenses().their_word("Marcus")
        promised = out.get("promised") or []
        assert any("survey" in str(r.get("summary", "")).lower()
                   for r in promised), out

    def test_the_lens_can_compare_a_new_claim_against_the_old_one(self, brain):
        """`they_said(person, claim)` is the whole reframe: both sides are quotes
        the wearer can read, and it needs a prior utterance attributed to that
        person to have anything to compare with."""
        ear = EarHost(brain)
        ear.ingest_caption("the roof was replaced last year", speaker="Marcus")
        out = brain.lenses().they_said("Marcus", "the roof has never been replaced",
                                       push=False)
        assert out.get("prior") or out.get("said") or out.get("items"), out


class TestTheVeilStillWins:

    def test_a_veiled_utterance_is_attributed_nowhere(self, brain):
        """Attribution changes nothing about the shield: while incognito the
        utterance is not stored at all, so there is no `said_by` to argue about."""
        brain.incognito_now = lambda: True
        EarHost(brain).ingest_caption("I'll send the lease", speaker="Marcus")
        assert _metas(brain) == []
