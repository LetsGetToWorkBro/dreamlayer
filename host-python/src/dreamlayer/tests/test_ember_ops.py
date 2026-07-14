"""Ember on the Orchestrator — place-gated prompts, the spoken reach, the
veil contract, the nightly ride-along, and the consent-only burn."""

import pytest

from dreamlayer.ember import RecallOutcome, next_review
from dreamlayer.main import build
from dreamlayer.pipelines.ingest import MemoryEvent

NOW = 1_700_000_000.0
DAY = 86400.0

CUE = "What did Maya say?"
ANSWER = "Maya said her first full sentence in Spanish"


def orc_with_engram(sig="sig-kitchen", kept_days_ago=4.0):
    orc = build()
    orc._clock = lambda: NOW
    e = orc.embers.keep("k1", CUE, ANSWER, NOW - kept_days_ago * DAY,
                       place_signature=sig)
    return orc, e


class TestPrompt:
    def test_place_match_fires_the_prompt(self):
        orc, _ = orc_with_engram()
        card = orc.on_place("sig-kitchen")
        assert card["type"] == "EmberPromptCard"
        assert orc.bridge.last_card["type"] == "EmberPromptCard"

    def test_the_cue_never_carries_the_answer(self):
        orc, _ = orc_with_engram()
        card = orc.on_place("sig-kitchen")
        assert "Spanish" not in str(card), \
            "the reveal card is the only surface that may render the answer"

    def test_wrong_doorway_stays_silent(self):
        orc, _ = orc_with_engram()
        assert orc.on_place("sig-office") is None

    def test_prompts_never_stack(self):
        orc, _ = orc_with_engram()
        orc.embers.keep("k2", "What did you promise?", "the lease",
                       NOW - 4 * DAY, place_signature="sig-kitchen")
        assert orc.on_place("sig-kitchen") is not None
        assert orc.tick_ember() is None, "one glow holds the floor"

    def test_paused_veil_blocks_the_prompt(self):
        orc, _ = orc_with_engram()
        orc.pause()
        assert orc.tick_ember(place_signature="sig-kitchen") is None
        orc.resume()
        assert orc.tick_ember(place_signature="sig-kitchen") is not None


class TestReach:
    def test_spoken_recall_routes_flares_and_advances(self):
        orc, e = orc_with_engram()
        orc.on_place("sig-kitchen")
        res = orc.handle_voice("she said her first full sentence in spanish")
        assert res["intent"] == "ember"
        assert res["outcome"] in ("good", "easy")
        assert orc.bridge.last_card["type"] == "EmberFlareCard"
        assert orc.embers.get(e.id).state.reps == e.state.reps + 1

    def test_wake_word_always_bypasses_the_glow(self):
        orc, e = orc_with_engram()
        orc.on_place("sig-kitchen")
        res = orc.handle_voice("hey juno, where are my keys")
        assert res.get("intent") == "locate"
        assert orc.embers.get(e.id).state.reps == e.state.reps, \
            "addressing Juno is never graded"

    def test_i_dont_remember_reveals_and_records_a_lapse(self):
        orc, e = orc_with_engram()
        orc.on_place("sig-kitchen")
        res = orc.handle_voice("i don't remember")
        assert res["outcome"] == "forgot"
        assert orc.bridge.last_card["type"] == "EmberRevealCard"
        assert orc.bridge.last_card["answer"] == ANSWER
        assert orc.embers.get(e.id).state.lapses == 1

    def test_not_now_is_a_missed_never_a_lapse(self):
        orc, e = orc_with_engram()
        orc.on_place("sig-kitchen")
        res = orc.handle_voice("not now")
        assert res["outcome"] == "missed"
        assert orc.embers.get(e.id).state.lapses == 0

    def test_a_wrong_reach_reveals_gently(self):
        orc, _ = orc_with_engram()
        orc.on_place("sig-kitchen")
        res = orc.handle_voice("um, something about the weather maybe")
        assert res["outcome"] == "forgot"
        assert orc.bridge.last_card["type"] == "EmberRevealCard"

    def test_expired_prompt_never_swallows_ordinary_speech(self):
        orc, e = orc_with_engram()
        orc.on_place("sig-kitchen")
        later = NOW + 120.0                      # well past ATTEMPT_WINDOW_S
        orc._clock = lambda: later
        res = orc.handle_voice("where are my keys")
        assert res.get("intent") == "locate"
        # and the expiry itself was a MISSED on the curve, not a lapse
        assert orc.embers.get(e.id).state.lapses == 0

    def test_graduation_sends_the_offer_card(self):
        orc, e = orc_with_engram()
        st = e.state
        while True:                               # walk to the brink
            nxt = next_review(st, RecallOutcome.EASY, st.due_ts)
            if nxt.graduated:
                break
            st = nxt
        orc.embers._write_state(e.id, st)
        orc._clock = lambda: st.due_ts
        assert orc.tick_ember(place_signature="sig-kitchen") is not None
        res = orc.handle_voice("she said her first full sentence in spanish")
        assert res["graduated"] is True and res.get("offer") is True
        assert orc.bridge.last_card["type"] == "EmberGraduatedCard"


class TestTendingRitual:
    def a_ring(self, orc):
        orc.ring.append(MemoryEvent(kind="promise",
                                    summary="send Marcus the lease by Friday",
                                    confidence=0.9), ts=NOW - 10 * 3600)
        orc.ring.append(MemoryEvent(kind="conversation", summary=ANSWER,
                                    confidence=0.9), ts=NOW - 7 * 3600)

    def test_morning_tending_stages_offers(self):
        orc = build(); orc._clock = lambda: NOW
        self.a_ring(orc)
        offers = orc.morning_tending()
        assert offers and orc.tending_candidates()

    def test_veiled_evening_stages_nothing(self):
        orc = build(); orc._clock = lambda: NOW
        self.a_ring(orc)
        orc.pause()
        assert orc.morning_tending() == []

    def test_keep_creates_the_engram_let_go_releases(self):
        orc = build(); orc._clock = lambda: NOW
        self.a_ring(orc)
        offers = orc.morning_tending()
        row = orc.tend_keep(offers[0].id)
        assert row and row["cue"] == offers[0].cue
        assert orc.tend_let_go(offers[1].id) is True
        assert orc.tend_let_go(offers[1].id) is False   # single-shot

    def test_keeps_are_capped_per_day(self):
        from dreamlayer.ember.tending import MAX_KEEPS_PER_DAY
        orc = build(); orc._clock = lambda: NOW
        orc.ring.extend([MemoryEvent(kind="memory",
                                     summary=f"a fine moment number {i}",
                                     confidence=0.9) for i in range(8)],
                        ts=NOW - 3600)
        offers = orc.morning_tending()
        kept = [orc.tend_keep(c.id) for c in offers]
        assert sum(1 for k in kept if k) == MAX_KEEPS_PER_DAY, \
            "tending is a ritual, not an inbox"

    def test_the_night_stages_before_the_ring_is_swept(self, tmp_path):
        import dreamlayer.config as C
        from dreamlayer.bridge.emulator_bridge import EmulatorBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        import time as _t
        if not (_t.localtime(NOW).tm_hour >= 22 or _t.localtime(NOW).tm_hour < 6):
            pytest.skip("NightWatch gate needs a night-local hour")
        cfg = C.Config()
        cfg.vault_dir = str(tmp_path)
        orc = Orchestrator(EmulatorBridge(), config=cfg)
        orc._clock = lambda: NOW
        self.a_ring(orc)
        reel = orc.maybe_dream_tonight(charging=True)
        assert reel is not None
        assert orc.last_tending, "offers must stage before purge_hot"
        assert len(orc.ring) == 0


class TestCeremony:
    def graduated_orc(self):
        orc = build(); orc._clock = lambda: NOW
        mid = orc.db.add_memory("conversation", ANSWER, confidence=0.9)
        e = orc.embers.keep("k1", CUE, ANSWER, NOW, source_memory_id=mid)
        st = e.state
        while not st.graduated:
            st = next_review(st, RecallOutcome.EASY, st.due_ts)
        orc.embers._write_state(e.id, st)
        return orc, e, mid

    def test_burn_requires_explicit_consent(self):
        orc, e, _ = self.graduated_orc()
        with pytest.raises(ValueError):
            orc.burn_ember(e.id)
        with pytest.raises(ValueError):
            orc.burn_ember(e.id, consent=None)

    def test_ungraduated_engrams_cannot_burn(self):
        orc = build(); orc._clock = lambda: NOW
        e = orc.embers.keep("k1", CUE, ANSWER, NOW)
        with pytest.raises(ValueError):
            orc.burn_ember(e.id, consent=True)

    def test_burn_purges_source_blanks_answer_plants_tombstone(self):
        import json
        orc, e, mid = self.graduated_orc()
        receipt = orc.burn_ember(e.id, consent=True)
        assert orc.db.memory(mid) is None, "the recording must actually go"
        burned = orc.embers.get(e.id)
        assert burned.burned and burned.answer == ""
        tomb = orc.db.memory(receipt["tombstone_memory_id"])
        assert tomb["kind"] == "ember" and tomb["summary"] == CUE
        meta = json.loads(tomb["meta"])
        assert meta["pinned"] and meta["ember_tombstone"]
        assert ANSWER not in str(tomb), "a tombstone holds only the cue"

    def test_offers_lists_exactly_the_burnable(self):
        orc, e, _ = self.graduated_orc()
        assert [o["id"] for o in orc.ember_offers()] == [e.id]
        orc.burn_ember(e.id, consent=True)
        assert orc.ember_offers() == []

    def test_status_reads_the_whole_practice(self):
        orc, e, _ = self.graduated_orc()
        s = orc.ember_status()
        assert s["tended"] == 1 and s["graduated"] == 1 and s["burned"] == 0
