"""test_brain_lens_wiring.py — the lenses are CALLED, not merely constructible.

`test_brain_lens_hosts.py` proved the seven lenses in `lens_hosts.py` build and
answer when a test hands them state. It did not prove anything in the product
ever hands them state, and it turned out nothing did: `brain.lenses()` had one
production call site — inside `purge_memories()`, which nulls the set two lines
later — so on a shipped Brain no lens object was ever constructed at all. Every
one of them was importable-never-called, which is `decisions/0001` verbatim, one
layer up. `scripts/lens_reachability.py` listed all seven as "reachable" the
whole time, exactly as its own header warns it would.

So this file tests the OTHER half, and it tests it the way that gap could only
have been caught: nothing here calls a lens directly. Every test drives a real
`Brain` through the surface a wearer touches — the ear, an HTTP route, a spoken
intent, a retention sweep — and asserts the lens moved. Delete any single wiring
line added with this file and a test here goes red.

The three failure modes being pinned down, in order of how badly they lie:

  1. A lens with no caller. It never runs, so it never contradicts you, never
     finds a source, never says a promise is slipping. It agrees with you
     forever, which reads exactly like a lens that works.
  2. A lens fed the wrong input. `via="said"` on the room ear would make
     Provenance claim you witnessed whatever a stranger nearby mentioned.
  3. A store that survives an erase. `quest_log.json` is a behavioural record of
     how reliably you keep your word, and it used to outlive
     erase-everything.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.store import BrainConfig


@pytest.fixture(autouse=True)
def _no_db_override(monkeypatch):
    monkeypatch.delenv("DREAMLAYER_DB", raising=False)


def _brain(tmp_path) -> Brain:
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    BrainConfig(token="tok").save(cfg)
    return Brain(cfg)


class _Live:
    """A real Brain behind a real socket. The lens routes are token-gated (the
    phone is the surface), so every call carries the header."""

    def __init__(self, tmp_path, token="tok"):
        cfg = tmp_path / "cfg"
        cfg.mkdir(exist_ok=True)
        BrainConfig(token=token).save(cfg)
        self.brain = Brain(cfg)
        self.server = make_brain_server(self.brain, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.h = {"X-DreamLayer-Token": token}

    def get(self, path):
        req = urllib.request.Request(self.url + path, headers=self.h)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, None

    def post(self, path, payload):
        req = urllib.request.Request(
            self.url + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **self.h})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, None

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def live(tmp_path):
    lb = _Live(tmp_path)
    yield lb
    lb.stop()


# ---------------------------------------------------------------------------
# 1. The ring is fed. Everything else depends on this one.
# ---------------------------------------------------------------------------

class TestTheEarFeedsTheRing:
    """The gap that made all seven lenses inert: `observe()` had no caller.

    These drive `EarHost.ingest_caption`, which is what the real capture loop
    calls for every transcribed utterance — not `observe()`, and not
    `ingest_utterance()`. Nothing here reaches into `lens_hosts` directly.
    """

    def _ear(self, brain):
        from dreamlayer.ai_brain.server.ear import EarHost
        return EarHost(brain)

    def test_hearing_something_puts_it_in_the_statement_ring(self, tmp_path):
        b = _brain(tmp_path)
        assert len(b.lenses().ring) == 0
        self._ear(b).ingest_caption("the venue is booked for Friday")
        assert len(b.lenses().ring) > 0, (
            "the ear heard an utterance and the statement ring stayed empty — "
            "every ring lens will now report 'nothing to say' forever")

    def test_the_utterance_itself_is_findable_in_the_ring(self, tmp_path):
        b = _brain(tmp_path)
        self._ear(b).ingest_caption("the deposit was paid on Friday")
        said = [x.event.summary for x in b.lenses().ring.latest(limit=50)]
        assert any("deposit" in s for s in said), said

    def test_the_ear_is_second_hand_never_firsthand(self, tmp_path):
        """`via` decides whether Provenance says you WITNESSED this. The room
        ear is ambient audio in front of the wearer, so it must never claim
        firsthand — that would attribute a bystander's remark to the wearer's
        own eyes."""
        from dreamlayer.orchestrator.provenance import _FIRSTHAND_VIA
        b = _brain(tmp_path)
        self._ear(b).ingest_caption("Ana mentioned the caterer cancelled")
        vias = {(x.event.meta or {}).get("via")
                for x in b.lenses().ring.latest(limit=50)}
        assert vias, "nothing landed in the ring at all"
        assert not (vias & _FIRSTHAND_VIA), (
            f"the room ear marked something firsthand: {vias}")

    def test_the_veil_stops_the_ear_before_the_ring(self, tmp_path,
                                                    monkeypatch):
        b = _brain(tmp_path)
        monkeypatch.setattr(b, "incognito_now", lambda: True)
        self._ear(b).ingest_caption("the venue is booked")
        assert len(b.lenses().ring) == 0, (
            "an utterance reached the ring while the veil was down")

    def test_a_commitment_lands_as_a_task_row_not_a_blob(self, tmp_path):
        """Commitment Drift reads `ring.latest(kind='task')` and nothing else.
        A ring of undifferentiated 'heard' lines leaves Drift and Saga
        permanently empty however much is said."""
        b = _brain(tmp_path)
        self._ear(b).ingest_caption("I need to send Maya the deck")
        kinds = {x.event.kind for x in b.lenses().ring.latest(limit=50)}
        assert "task" in kinds, (
            f"no task extracted from a plain commitment; ring holds {kinds}")

    def test_the_lens_set_is_built_outside_erase_everything(self, tmp_path):
        """The structural half of the bug: `_lenses` was set by exactly one
        production path — `purge_memories`, which nulls it two lines later — so
        the attribute was None at every moment anything could observe it.

        Booting a Brain must now leave one live (the retention sweep builds it),
        and the ear must append to THAT instance rather than a second set that
        nothing else can see."""
        b = _brain(tmp_path)
        at_boot = getattr(b, "_lenses", None)
        assert at_boot is not None, "no lens set survives boot"
        self._ear(b).ingest_caption("the venue is booked")
        assert b.lenses() is at_boot, "the ear fed a different lens set"
        assert len(at_boot.ring) > 0


# ---------------------------------------------------------------------------
# 2. Candor — with a caller on the utterance path
# ---------------------------------------------------------------------------

class TestCandorRunsOnWhatYouSay:

    def _ear(self, brain):
        from dreamlayer.ai_brain.server.ear import EarHost
        return EarHost(brain)

    def test_contradicting_yourself_fires_candor_through_the_ear(self, tmp_path):
        b = _brain(tmp_path)
        ear = self._ear(b)
        ear.ingest_caption("the venue is booked for Friday")
        out = ear.brain.lenses().ingest_utterance(
            "the venue is not booked for Friday", via="heard")
        assert out["candor"] is not None and out["candor"]["fired"], out
        assert "booked" in out["candor"]["prior"]

    def test_the_prior_statement_survives_to_the_card_footer(self, tmp_path):
        """Candor's whole proposition lives in the FOOTER — "you said different
        before" with no "before" in it is not the lens. Every shipped fallback
        renderer drops footers, so the card must carry it explicitly and this
        pins it."""
        b = _brain(tmp_path)
        ls = b.lenses()
        ls.ingest_utterance("the deposit was paid", via="said")
        out = ls.candor_check("the deposit was not paid")
        assert out["fired"]
        assert out["card"]["footer"] == "the deposit was paid"

    def test_a_negated_sentence_does_not_contradict_itself(self, tmp_path):
        """Order regression. Extraction rewrites "I won't pay the deposit" into
        a task row that drops the negator; checking the line against a fragment
        of ITSELF fires on every negated sentence a wearer says. Candor has to
        run before the utterance enters the ring."""
        b = _brain(tmp_path)
        out = b.lenses().ingest_utterance(
            "I will not pay the deposit this week", via="said")
        assert out["candor"] is not None
        assert not out["candor"]["fired"], out["candor"]

    def test_candor_answers_null_under_the_veil_never_all_clear(self, tmp_path,
                                                                monkeypatch):
        """`None` and `{"fired": False}` are different answers. A veiled lens
        that returns "no contradiction" is telling the wearer their story hangs
        together when it was never allowed to look."""
        b = _brain(tmp_path)
        ls = b.lenses()
        ls.ingest_utterance("the venue is booked", via="said")
        monkeypatch.setattr(b, "incognito_now", lambda: True)
        assert ls.candor_check("the venue is not booked") is None


# ---------------------------------------------------------------------------
# 3. Provenance — fed real `via`, so the status space is not degenerate
# ---------------------------------------------------------------------------

class TestProvenanceAnswersAboutRealInput:

    def test_a_deliberate_statement_traces_as_firsthand(self, live):
        """`status="firsthand"` was unreachable: nothing wrote `meta["via"]`, so
        it always resolved to the literal "recorded" and `_FIRSTHAND_VIA` could
        never match. The wearer's own POST is the firsthand path."""
        live.post("/dreamlayer/lens/observe",
                  {"text": "the venue is booked for Friday"})
        st, body = live.get("/dreamlayer/provenance?claim=the+venue+is+booked")
        assert st == 200, st
        r = body["result"]
        assert r["found"], r
        assert r["status"] == "firsthand", r["status"]

    def test_something_overheard_is_not_firsthand(self, tmp_path):
        b = _brain(tmp_path)
        from dreamlayer.ai_brain.server.ear import EarHost
        EarHost(b).ingest_caption("the caterer cancelled on Thursday")
        r = b.lenses().trace("the caterer cancelled")
        assert r["found"], r
        assert r["status"] != "firsthand", r

    def test_an_unheard_claim_is_not_found_rather_than_invented(self, live):
        st, body = live.get("/dreamlayer/provenance?claim=the+moon+is+cheese")
        assert st == 200
        assert body["result"]["found"] is False

    def test_the_veil_is_null_not_not_found(self, tmp_path, monkeypatch):
        b = _brain(tmp_path)
        b.lenses().ingest_utterance("the venue is booked", via="said")
        monkeypatch.setattr(b, "incognito_now", lambda: True)
        assert b.lenses().trace("the venue is booked") is None


# ---------------------------------------------------------------------------
# 4. Commitment Drift + Saga — a clock, and badges that can unlock
# ---------------------------------------------------------------------------

class TestCommitmentsMoveAndPay:

    def test_a_spoken_commitment_becomes_a_tracked_record(self, live):
        live.post("/dreamlayer/lens/observe",
                  {"text": "I need to send Maya the deck"})
        st, body = live.get("/dreamlayer/drift")
        assert st == 200 and body["ok"], body
        assert body["records"], "a commitment was spoken and nothing tracks it"

    def test_the_same_commitment_shows_up_as_a_quest(self, live):
        live.post("/dreamlayer/lens/observe",
                  {"text": "I need to send Maya the deck"})
        st, body = live.get("/dreamlayer/quests")
        assert st == 200 and body["ok"], body
        assert body["quests"], body
        assert body["quests"][0]["card"]["type"] == "QuestCard"

    def test_completing_a_quest_pays_xp_through_the_route(self, live):
        live.post("/dreamlayer/lens/observe",
                  {"text": "I need to send Maya the deck"})
        st, body = live.post("/dreamlayer/quests/complete",
                             {"subject": "deck"})
        assert st == 200, st
        assert body["reward"] is not None, "the quest could not be completed"
        assert body["reward"]["xp"] > 0
        _, after = live.get("/dreamlayer/quests")
        assert after["stats"]["xp"] > 0

    def test_completing_a_quest_unlocks_the_keeper_badge(self, live):
        """The five quest achievements in `saga.py` are keyed to event ids
        (`quest_done`/`quest_rescue`/`streak`) that nothing in the codebase ever
        emitted, so the phone's badge grid rendered all five permanently locked
        and no user action could change it."""
        live.post("/dreamlayer/lens/observe",
                  {"text": "I need to send Maya the deck"})
        st, body = live.post("/dreamlayer/quests/complete", {"subject": "deck"})
        assert st == 200
        assert "Keeper" in (body["reward"]["badges_unlocked"] or []), body
        _, saga = live.get("/dreamlayer/saga")
        names = json.dumps(saga)
        assert "Keeper" in names, "the badge did not reach the Saga profile"

    def test_a_commitment_survives_the_24_hour_hot_purge(self, tmp_path):
        """The trap the cold-kind exemption exists for: the drift lifetime is
        48 h and due dates run days out, but `retention_hot_hours` is 24 h. An
        unexempted ring purge deletes in-force commitments and the lens reports
        the promise as never made."""
        from dreamlayer.ai_brain.server.retention_live import sweep_retention
        b = _brain(tmp_path)
        ls = b.lenses()
        old = time.time() - 30 * 3600          # older than hot, inside drift
        ls.observe("task", "Task: send Maya the deck", ts=old, confidence=0.7)
        ls.observe("heard", "nice weather today", ts=old, confidence=0.6)
        sweep_retention(b)
        kinds = [x.event.kind for x in ls.ring.latest(limit=50)]
        assert "task" in kinds, "a live commitment was aged out of the ring"
        assert "heard" not in kinds, "ordinary chatter outlived the hot window"


# ---------------------------------------------------------------------------
# 5. Stasis — the spoken trigger that used to be a working-looking no-op
# ---------------------------------------------------------------------------

class TestHoldThatThought:

    def test_saying_hold_that_thought_actually_holds_it(self, live):
        """`orchestrator/voice.py` has parsed this into `stasis_freeze` for as
        long as the grammar existed. `_post_voice` had no branch for it, so it
        fell to the default and returned a bare {"intent": "stasis_freeze"} —
        which `phone-app/app/now.tsx` renders as the literal text
        "(stasis_freeze)". 200 OK, nothing held."""
        live.post("/dreamlayer/lens/observe",
                  {"text": "the deposit needs paying before Friday"})
        st, body = live.post("/dreamlayer/voice", {"text": "hold that thought"})
        assert st == 200, st
        assert body.get("ok") is True, body
        assert body.get("id"), body
        _, frames = live.get("/dreamlayer/stasis")
        assert frames["frames"], "nothing was actually held"

    def test_where_was_i_hands_the_thought_back(self, live):
        live.post("/dreamlayer/lens/observe",
                  {"text": "the deposit needs paying before Friday"})
        live.post("/dreamlayer/voice", {"text": "hold that thought"})
        st, body = live.post("/dreamlayer/voice", {"text": "where was I"})
        assert st == 200 and body.get("ok") is True, body
        assert "deposit" in (body.get("utterance") or ""), body

    def test_a_held_thought_survives_a_restart(self, tmp_path):
        """A save state that does not survive a restart is not a save state,
        which is the entire premise of the lens."""
        b = _brain(tmp_path)
        b.lenses().ingest_utterance("the deposit needs paying", via="said")
        b.lenses().freeze()
        again = _brain(tmp_path)
        assert again.lenses().frames(), "the held thought did not persist"

    def test_pinning_keeps_a_thought_past_compost(self, tmp_path):
        b = _brain(tmp_path)
        ls = b.lenses()
        r = ls.freeze("a long-running thought")
        assert ls.pin(r["id"])
        assert ls.compost() == 0
        assert ls.frames()[0]["pinned"] is True

    def test_freezing_is_refused_under_the_veil(self, tmp_path, monkeypatch):
        b = _brain(tmp_path)
        monkeypatch.setattr(b, "incognito_now", lambda: True)
        assert b.lenses().freeze("something") is None


# ---------------------------------------------------------------------------
# 6. Premonition and Inner Weather — reachable over HTTP
# ---------------------------------------------------------------------------

class TestTheRemainingTwoAnswer:

    def test_premonition_is_reachable_and_honest_when_it_cannot_say(self, live):
        st, body = live.get("/dreamlayer/premonition")
        assert st == 200
        assert body["predictions"] == [], (
            "a fresh Brain claimed to predict something from no history")

    def test_inner_weather_reports_motion_it_is_actually_given(self, live):
        """The lens is not fed by the Brain — it has no IMU. The phone posts
        one, so the route is where it must be reachable, and a payload with
        real motion in it has to move the churn off zero. A lens that answers
        'calm' whatever you send is indistinguishable from one that works."""
        st, body = live.post("/dreamlayer/weather", {
            "imu_delta": {"yaw": 1.4, "pitch": 0.9, "roll": 0.7}})
        assert st == 200, st
        churn = [f for f in body["frames"] if f.get("mode") == "churn"]
        assert churn, body
        assert churn[0]["intensity"] > 0.0, churn

    def test_inner_weather_is_not_the_confluence_sky(self, live):
        """`/dreamlayer/live/weather` is Confluence's shared EntangledSky
        between two people. Grepping the route table for "weather" finds it and
        concludes Inner Weather is wired; it is a different lens entirely."""
        _, body = live.post("/dreamlayer/weather", {
            "imu_delta": {"yaw": 1.4, "pitch": 0.9, "roll": 0.7}})
        assert any(f.get("mode") == "churn" for f in body["frames"])


# ---------------------------------------------------------------------------
# 7. Retention reaches the statement ring, and reports what it took
# ---------------------------------------------------------------------------

class TestRetentionSweepsTheStatementRing:

    def test_old_statements_are_actually_gone_after_a_sweep(self, tmp_path):
        from dreamlayer.ai_brain.server.retention_live import sweep_retention
        b = _brain(tmp_path)
        ls = b.lenses()
        ls.observe("heard", "something said long ago",
                   ts=time.time() - 48 * 3600, confidence=0.6)
        ls.observe("heard", "something said just now", confidence=0.6)
        assert len(ls.ring) == 2
        sweep_retention(b)
        left = [x.event.summary for x in ls.ring.latest(limit=10)]
        assert left == ["something said just now"], left

    def test_the_sweep_finds_the_ring_without_being_handed_it(self, tmp_path):
        """`getattr(brain, "_lenses", None)` was None at every moment a sweep
        could observe it, so this leg never ran once in a shipped build. The
        sweep has to reach the ring through the same accessor everything else
        uses."""
        from dreamlayer.ai_brain.server.retention_live import sweep_retention
        b = _brain(tmp_path)
        b.lenses().observe("heard", "old chatter",
                           ts=time.time() - 48 * 3600, confidence=0.6)
        report = sweep_retention(b)
        assert report["hot_purged"] >= 1, report

    def test_both_hot_stores_are_counted_not_one_overwriting_the_other(
            self, tmp_path):
        """The report line the wearer reads ("N sighting(s) past 24h") is the
        privacy disclosure for a deletion nobody asked for. A plain `=` on the
        second store silently dropped the first store's count from it."""
        from dreamlayer.ai_brain.server.retention_live import sweep_retention
        from dreamlayer.memory.ring_buffer import SemanticRingBuffer
        from dreamlayer.pipelines.ingest import MemoryEvent
        b = _brain(tmp_path)
        old = time.time() - 48 * 3600
        b.lenses().observe("heard", "old chatter", ts=old, confidence=0.6)

        class _WL:                       # the sighting ring, as world_lens holds it
            ring = SemanticRingBuffer(16)
        _WL.ring.append(MemoryEvent(kind="object", summary="a mug"), ts=old)
        b._world_lens = _WL()

        report = sweep_retention(b)
        assert report["hot_purged"] == 2, (
            f"one hot store's count overwrote the other: {report}")

    def test_a_sweep_does_not_open_the_store_for_an_unused_lens_set(
            self, tmp_path):
        """`purge_hot` reading `self.ring` would SEED from the memory database.
        An hourly background sweep must not be what opens the store on a Brain
        that has used no lens."""
        from dreamlayer.ai_brain.server.retention_live import sweep_retention
        b = _brain(tmp_path)
        sweep_retention(b)
        assert b.lenses()._ring is None, "the sweep built and seeded the ring"


# ---------------------------------------------------------------------------
# 8. Erase-everything reaches all of it
# ---------------------------------------------------------------------------

class TestEraseReachesTheLenses:

    def test_the_quest_tally_does_not_survive_an_erase(self, tmp_path):
        """`QuestLog` writes `<cfg_dir>/vault/quest_log.json` and re-reads it on
        next construction, so an erase-everything used to leave xp, streak and
        unlocked achievements on disk — a behavioural record of how reliably the
        wearer keeps their word, surviving the one action that promises to
        remove everything."""
        b = _brain(tmp_path)
        ls = b.lenses()
        ls.ingest_utterance("I need to send Maya the deck", via="said")
        assert ls.quest_complete("deck") is not None
        assert ls.quest_path.exists()

        b.purge_memories()

        fresh = _brain(tmp_path).lenses()
        assert not fresh.quest_path.exists(), "quest_log.json survived the erase"
        assert fresh.quests()["stats"]["xp"] == 0, fresh.quests()["stats"]

    def test_held_thoughts_and_statements_do_not_survive_an_erase(self, tmp_path):
        b = _brain(tmp_path)
        ls = b.lenses()
        ls.ingest_utterance("the deposit needs paying", via="said")
        ls.freeze()
        b.purge_memories()
        fresh = _brain(tmp_path).lenses()
        assert fresh.frames() == []
        assert len(fresh.ring) == 0

    def test_erasing_drops_the_in_memory_lenses_too(self, tmp_path):
        """A cached `saga` holds the tally in memory and a cached `drift` holds
        records keyed to ring buckets. Keeping either past a wipe means the next
        read answers from state the wearer just erased."""
        b = _brain(tmp_path)
        ls = b.lenses()
        ls.ingest_utterance("I need to send Maya the deck", via="said")
        ls.quest_complete("deck")
        ls.forget_all()
        assert ls.quests()["stats"]["xp"] == 0


# ---------------------------------------------------------------------------
# 9. The routes exist, are token-gated, and are honest about the veil
# ---------------------------------------------------------------------------

class TestTheRoutesAreReachable:

    LENS_GETS = ["/dreamlayer/lenses", "/dreamlayer/provenance?claim=x",
                 "/dreamlayer/quests", "/dreamlayer/drift",
                 "/dreamlayer/stasis", "/dreamlayer/premonition"]
    LENS_POSTS = ["/dreamlayer/lens/observe", "/dreamlayer/candor/check",
                  "/dreamlayer/drift/tend", "/dreamlayer/quests/complete",
                  "/dreamlayer/quests/abandon", "/dreamlayer/stasis/freeze",
                  "/dreamlayer/stasis/resume", "/dreamlayer/stasis/pin",
                  "/dreamlayer/weather"]

    def test_every_lens_route_answers(self, live):
        for path in self.LENS_GETS:
            st, _ = live.get(path)
            assert st == 200, f"GET {path} → {st}"
        for path in self.LENS_POSTS:
            st, _ = live.post(path, {"text": "x", "claim": "x", "subject": "x"})
            assert st == 200, f"POST {path} → {st}"

    def test_no_lens_route_answers_without_the_token(self, live):
        live.h = {}
        for path in self.LENS_GETS:
            st, _ = live.get(path)
            assert st in (401, 403), f"GET {path} answered unauthenticated: {st}"
        for path in self.LENS_POSTS:
            st, _ = live.post(path, {})
            assert st in (401, 403), f"POST {path} answered unauthenticated: {st}"

    def test_the_status_route_does_not_seed_the_ring(self, live):
        st, body = live.get("/dreamlayer/lenses")
        assert st == 200
        assert body["ring"] == 0 and body["seeded"] is False, body

    def test_the_status_route_reports_the_veil(self, live, monkeypatch):
        monkeypatch.setattr(live.brain, "incognito_now", lambda: True)
        _, body = live.get("/dreamlayer/lenses")
        assert body["veiled"] is True
