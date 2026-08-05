"""Four cards that were recorded as blocked and were not.

Every one of these was listed under a blocker in HANDOFF, and in each case the
blocker was my own mis-read rather than a missing capability — the same error
made about `TimeScrubNodeCard` ("needs a durable store the Brain lacks", when
the hot ring already was the day).

  * ProactiveMemoryCard and CommitmentRecallCard were filed under "needs
    speaker attribution". Both builders take `person` OPTIONALLY. Neither
    needs to know who spoke; with no attribution the card omits a footer,
    which is the honest rendering of "you owe this" rather than "you owe this
    to X". The data — an FSRS rehearsal store and a drift engine — already
    ships and is already routed.
  * ConsentRequiredCard was filed under "the consent decision". The consent
    MECHANISM already exists (`face_live.CONSENT_VERSION`, `POST
    /dreamlayer/face/consent`), and `identify()`/`enrol()` already refuse with
    `no-consent`. Nothing drew the refusal, so the wearer got silence where
    the product promises a question.
  * ForgetLastCard was filed under "needs a confirm gesture path" — which was
    true, and the answer is to build the path, not to push a question nobody
    can answer.
"""
from __future__ import annotations

import tempfile
import time

import pytest

from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.pipelines.ingest import MemoryEvent


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _pushes(brain):
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card)) or 1)
    return seen


# --- what you owe -----------------------------------------------------------

class TestWhatYouOwe:

    def _promise(self, ls, summary, person="", conf=0.8):
        ls.ring.append(MemoryEvent(kind="task", summary=summary, confidence=conf,
                                   meta={"person": person} if person else {}))

    def test_it_answers_with_no_speaker_attribution_at_all(self, brain):
        """The claim that filed this as blocked. No `person` anywhere, and the
        card still renders — it simply carries no footer."""
        ls = brain.lenses()
        self._promise(ls, "return the library book")
        seen = _pushes(brain)
        out = ls.owed()
        assert out["items"] and out["pushed"] == 1
        _kind, card = seen[-1]
        assert card["type"] == "CommitmentRecallCard"
        assert card["primary"] == "return the library book"
        assert not card.get("person")

    def test_the_person_rides_along_when_there_is_one(self, brain):
        ls = brain.lenses()
        self._promise(ls, "send the invoice", person="Ana")
        seen = _pushes(brain)
        ls.owed()
        assert seen[-1][1]["person"] == "Ana"

    def test_a_promise_with_no_due_date_sorts_last_not_first(self, brain):
        """`due_ts` of None coerced to 0 reads as "due at the epoch", i.e.
        maximally overdue — so an undated someday-maybe would outrank a real
        deadline and be the one card the wearer gets.

        The fixture needs BOTH kinds present or it proves nothing: an earlier
        version created two undated promises and asserted conditionally, so it
        passed against a mutant that sorted undated first. `_parse_due`
        understands "Xh"/"Xd"/"tomorrow", so "2h" gives a real due_ts.
        """
        ls = brain.lenses()
        # DATED FIRST, so ring order (newest-first) puts it LAST and only the
        # sort can bring it to the front. Appending it second made the test
        # pass with the sort deleted outright.
        ls.ring.append(MemoryEvent(kind="task", summary="call the dentist back",
                                   confidence=0.8, meta={"due": "2h"}))
        ls.ring.append(MemoryEvent(kind="task", summary="someday learn welding",
                                   confidence=0.8, meta={}))
        out = ls.owed(push=False)
        subjects = [i["subject"] for i in out["items"]]
        assert set(subjects) == {"someday learn welding", "call the dentist back"}

        dated = [i for i in out["items"] if i.get("due_ts")]
        undated = [i for i in out["items"] if not i.get("due_ts")]
        assert dated and undated, (
            f"fixture no longer has one of each: {out['items']}")
        assert out["items"][0]["subject"] == "call the dentist back", (
            f"an undated promise outranked a real deadline: {subjects}")

    def test_the_card_drawn_is_the_most_urgent_one(self, brain):
        """`owed` pushes the TOP row, so the sort order decides what the wearer
        actually sees — the assertion above only matters because of this."""
        ls = brain.lenses()
        # DATED FIRST, so ring order (newest-first) puts it LAST and only the
        # sort can bring it to the front. Appending it second made the test
        # pass with the sort deleted outright.
        ls.ring.append(MemoryEvent(kind="task", summary="call the dentist back",
                                   confidence=0.8, meta={"due": "2h"}))
        ls.ring.append(MemoryEvent(kind="task", summary="someday learn welding",
                                   confidence=0.8, meta={}))
        seen = _pushes(brain)
        ls.owed()
        assert seen[-1][1]["primary"] == "call the dentist back"

    def test_a_resolved_promise_is_not_something_you_owe(self, brain):
        """`resolved` is None while open, not False. A truth test would read a
        promise resolved at ts 0.0 as still open."""
        ls = brain.lenses()
        self._promise(ls, "pay the deposit")
        ls.drift.tick()
        for r in ls.drift.all_records():
            r.resolved = 0.0                       # resolved, at the epoch
        assert ls.owed(push=False)["items"] == []

    def test_the_veil_answers_nothing(self, brain):
        """INVERTED by decisions/0009 — "what do I owe?" is a read of the
        wearer's own promises, and recall is unrestricted."""
        ls = brain.lenses()
        self._promise(ls, "pay the deposit")
        brain.config.network_mode = "lan_only"
        _pushes(brain)
        assert ls.owed()["items"]

    def test_it_does_not_displace_commitment_drift(self, brain):
        """Both read the same store and both must stay. Drift FIRES when a
        promise slips; this ANSWERS "what do I owe?". Opposite directions."""
        ls = brain.lenses()
        self._promise(ls, "send the invoice")
        assert ls.owed(push=False)["items"]
        assert ls.drift_tick(push=False) is not None


# --- it remembers for you ---------------------------------------------------

class TestItRemembersForYou:

    def _due_now(self, brain, name, note):
        brain.rehearse_person(name, note)
        for item in brain._rehearsal()._items.values():
            item["due_ts"] = time.time() - 10       # overdue
        return brain._rehearsal()

    def test_a_due_rehearsal_becomes_a_card(self, brain):
        ls = brain.lenses()
        self._due_now(brain, "Sarah Chen", "from Acme")
        seen = _pushes(brain)
        out = ls.resurface()
        assert out["pushed"] == 1
        _kind, card = seen[-1]
        assert card["type"] == "ProactiveMemoryCard"
        assert "Sarah Chen" in card["primary"]

    def test_nothing_due_draws_nothing(self, brain):
        """An empty feed is silence, not a card saying "nothing"."""
        ls = brain.lenses()
        seen = _pushes(brain)
        assert ls.resurface()["pushed"] == 0
        assert seen == []

    def test_confidence_follows_reps_and_is_capped(self, brain):
        """A name reviewed many times is one the Brain is surer of — but a long
        streak must not render as certainty about a memory the wearer may still
        have lost."""
        ls = brain.lenses()
        store = self._due_now(brain, "Marcus", "climbing partner")
        for item in store._items.values():
            item["reps"] = 50
        seen = _pushes(brain)
        ls.resurface()
        assert seen[-1][1]["confidence"] <= 0.9

    def test_the_veil_answers_nothing(self, brain):
        ls = brain.lenses()
        self._due_now(brain, "Sarah Chen", "from Acme")
        brain.config.network_mode = "lan_only"
        seen = _pushes(brain)
        # decisions/0009 — resurfacing what you already know about someone is
        # a read of your own store.
        del seen
        assert ls.resurface()["items"]


# --- ask first --------------------------------------------------------------

class TestAskFirst:

    def test_a_refused_identify_draws_the_question(self, brain):
        from dreamlayer.ai_brain.server.face_live import FaceRecall
        fr = FaceRecall(brain)
        assert fr.consented is False               # nothing accepted yet
        seen = _pushes(brain)
        res = fr.identify(object())
        assert res["reason"] == "no-consent"
        _kind, card = seen[-1]
        assert card["type"] == "ConsentRequiredCard"
        # "Allow access?" with no object is a question nobody can answer
        assert "face" in card["detail"].lower()

    def test_the_card_never_pierces_the_veil(self, brain):
        """Under the shield nothing is being captured, so there is no access to
        ask about — and `identify` returns on the veil branch first."""
        from dreamlayer.ai_brain.server.face_live import FaceRecall
        brain.config.network_mode = "lan_only"
        fr = FaceRecall(brain)
        seen = _pushes(brain)
        assert fr.identify(object())["reason"] == "veiled"
        assert seen == []

    def test_it_draws_the_state_and_cannot_grant_anything(self, brain):
        """The card is a pointer to `POST /dreamlayer/face/consent`, never a
        second path into acceptance."""
        import inspect
        from dreamlayer.ai_brain.server.face_live import FaceRecall
        src = inspect.getsource(FaceRecall._ask_consent)
        body = src.split('"""')[-1]
        for banned in ("face_consent_version", "accept", "CONSENT_VERSION ="):
            assert banned not in body, f"the card grants consent: {banned}"


# --- forget that ------------------------------------------------------------

class TestForgetThat:

    def _remember(self, brain, text, kind="conversation"):
        _r, db = brain._retriever_for_purge()
        if db is None:
            from dreamlayer.memory.db import MemoryDB
            from dreamlayer.ai_brain.server.retention_live import _memory_db_path
            db = MemoryDB(str(_memory_db_path(brain)))
        db.add_memory(kind, text)
        return db

    def test_the_preview_asks_and_erases_nothing(self, brain):
        db = self._remember(brain, "the deposit is 1200")
        before = len(db.memories())
        seen = _pushes(brain)
        out = brain.forget_last_preview()
        assert out["ok"] and out["label"] == "the deposit is 1200"
        assert len(db.memories()) == before, "the preview erased something"
        _kind, card = seen[-1]
        assert card["type"] == "ForgetLastCard"
        assert "cannot be undone" in card["footer"]

    def test_confirming_erases_it(self, brain):
        db = self._remember(brain, "the deposit is 1200")
        prev = brain.forget_last_preview(push=False)
        out = brain.forget_memory(prev["id"])
        assert out["ok"] and out["forgotten"] == 1
        assert not any(m["id"] == prev["id"] for m in db.memories())

    def test_the_id_echo_is_the_confirmation(self, brain):
        """A confirm meaning "the newest" would erase whatever landed in the
        meantime — the ear can push a new utterance between ask and answer."""
        db = self._remember(brain, "the deposit is 1200")
        prev = brain.forget_last_preview(push=False)
        self._remember(brain, "and the survey is booked")   # arrives after
        brain.forget_memory(prev["id"])
        left = [m["summary"] for m in db.memories()]
        assert "and the survey is booked" in left, "confirm erased the wrong row"
        assert "the deposit is 1200" not in left

    def test_a_double_confirm_is_not_an_error(self, brain):
        """A flaky connection re-sending the confirm must not read as a failure
        to erase — the memory is gone either way."""
        self._remember(brain, "the deposit is 1200")
        prev = brain.forget_last_preview(push=False)
        assert brain.forget_memory(prev["id"])["forgotten"] == 1
        again = brain.forget_memory(prev["id"])
        assert again["ok"] is True and again["forgotten"] == 0

    def test_a_bad_id_is_refused(self, brain):
        for bad in (None, "", "abc", {}):
            assert brain.forget_memory(bad)["ok"] is False

    def test_nothing_to_forget_says_so(self, brain):
        out = brain.forget_last_preview()
        assert out["ok"] is False
        assert out["reason"] in ("nothing-to-forget", "no-store")

    def test_the_veil_answers_nothing(self, brain):
        """Split in two by decisions/0009, and the split is the point.

        The PREVIEW is a read — naming your own last memory back to you — so it
        answers while veiled. The DELETE is a write, so it refuses. Before, the
        preview refused and `forget_memory` had no gate at all: the only thing
        protecting a deletion was that nothing would hand it an id.
        """
        self._remember(brain, "the deposit is 1200")
        brain.config.network_mode = "lan_only"
        _pushes(brain)
        preview = brain.forget_last_preview()
        assert preview.get("reason") != "veiled", "a read was refused"
        assert brain.forget_memory(preview.get("id") or 1)["reason"] == "veiled", (
            "a memory could be erased while the Veil was up")

    def test_forgetting_goes_through_the_full_cascade(self, brain):
        """The one that matters. `MemoryDB.purge_memory` alone leaves the
        embedding in the .usearch index — a memory the wearer was told is gone
        and that vector search still finds. `Retriever.purge_memory` is the
        primitive that moves row, ANN vector, alternate store and REM bias
        together, and its own docstring says so."""
        import inspect
        src = inspect.getsource(type(brain).forget_memory)
        body = src.split('"""')[-1]
        assert "retr.purge_memory(" in body
        assert "db.purge_memory(" not in body, (
            "forget bypassed the cascade and hit the DB directly")

    def test_the_routes_reach_both_halves(self, brain):
        from dreamlayer.ai_brain.server import server as srv
        text = open(srv.__file__, encoding="utf-8").read()
        assert '"/dreamlayer/forget/last": _get_forget_last,' in text
        assert '"/dreamlayer/forget/last": _post_forget_last,' in text
        assert '"/dreamlayer/owed": _get_owed,' in text
        assert '"/dreamlayer/resurface": _get_resurface,' in text


class TestPromisesAreCommitmentsToo:
    """The kind mismatch that made "what you owe" answer half the question.

    `pipelines/ingest.py` writes a spoken promise as `kind="promise"` (with meta
    carrying person, task and due) and only a "remind me to…" phrasing as
    `kind="task"`. Both `commitment_drift` and `tell` read `kind="task"` alone,
    so "I'll send Ana the invoice on Friday" — the archetypal commitment, and
    the only one that names a person — was invisible to them.

    It stayed invisible because the Orchestrator that owns those engines is
    never built, so nothing user-facing depended on it. `owed()` changed that:
    it answers a question the wearer ASKED, and an answer that silently omits
    every promise made to a person is worse than no answer at all.
    """

    def test_a_spoken_promise_reaches_what_you_owe(self, brain):
        ls = brain.lenses()
        ls.ingest_utterance("I will send Ana the invoice on Friday", via="said")
        subjects = [i["subject"] for i in ls.owed(push=False)["items"]]
        assert any("Ana" in s for s in subjects), subjects

    def test_the_promise_keeps_the_person_it_named(self, brain):
        """The reason this matters most: a promise's meta is RICHER than a
        task's — it is the only ring kind that records who it was made to."""
        ls = brain.lenses()
        ls.ingest_utterance("I will send Ana the invoice on Friday", via="said")
        rows = [i for i in ls.owed(push=False)["items"] if i["person"]]
        assert rows and rows[0]["person"] == "Ana"

    def test_a_reminder_still_reaches_it(self, brain):
        """The kind that already worked must not have been traded away."""
        ls = brain.lenses()
        ls.ingest_utterance("remind me to call the dentist tomorrow", via="said")
        subjects = [i["subject"] for i in ls.owed(push=False)["items"]]
        assert any("dentist" in s for s in subjects), subjects

    def test_ordinary_talk_is_not_a_commitment(self, brain):
        """The gate has to keep meaning something. A conversation line is not a
        promise, and widening the kind set must not have swept it in."""
        ls = brain.lenses()
        ls.ingest_utterance("the meeting moved to 4pm", via="said")
        assert ls.owed(push=False)["items"] == []

    def test_both_commitment_engines_read_the_same_kinds(self):
        """`tell.py` had the identical filter for the identical reason. Sharing
        one helper is what stops the two answering different questions about
        what counts as a promise."""
        import inspect
        from dreamlayer.orchestrator import tell
        from dreamlayer.orchestrator.commitment_drift import COMMITMENT_KINDS
        assert set(COMMITMENT_KINDS) == {"task", "promise"}
        src = inspect.getsource(tell.TellEngine._baseline)
        assert "_commitments(" in src
        assert 'kind="task"' not in src, "tell.py re-grew its own kind filter"
