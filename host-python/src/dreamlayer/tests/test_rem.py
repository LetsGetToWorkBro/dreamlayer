"""REM — the sleep cycle is functional: deterministic dreams, honest
consolidation, privacy at the door, and a brighter morning Horizon."""

import pytest

from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.orchestrator.horizon_composer import HorizonComposer
from dreamlayer.pipelines.ingest import MemoryEvent
from dreamlayer.rem import (
    REMCycle, RetrievalBias, DreamPoet, event_key, render_reel,
)
from dreamlayer.rem.bias import BIAS_MAX

NOW = 1_700_000_000.0
H = 3600.0


def ring_with(events, capacity=64):
    ring = SemanticRingBuffer(capacity=capacity)
    for hours_ago, kind, summary, conf, meta in events:
        ring.append(MemoryEvent(kind=kind, summary=summary,
                                confidence=conf, meta=meta or {}),
                    ts=NOW - hours_ago * H)
    return ring


def a_day():
    return ring_with([
        (12, "promise", "send Marcus the contract by Friday", 0.9, None),
        (11, "person",  "met Maya about the contract",        0.9, None),
        (9,  "memory",  "keys on the kitchen counter",        0.7, None),
        (4,  "memory",  "the gym clock is seven minutes fast", 0.6, None),
        (2,  "memory",  "watered the plants",                 0.30, None),
        (1,  "memory",  "a grey cat on the windowsill",       0.40, None),
    ])


class TestCycle:
    def test_same_seed_same_dreams(self):
        r1 = REMCycle(a_day(), seed=7, now_fn=lambda: NOW).run()
        r2 = REMCycle(a_day(), seed=7, now_fn=lambda: NOW).run()
        assert [s.phrase for s in r1.scenes] == [s.phrase for s in r2.scenes]
        assert r1.deltas == r2.deltas

    def test_different_seed_different_night(self):
        r1 = REMCycle(a_day(), seed=7, now_fn=lambda: NOW).run()
        r2 = REMCycle(a_day(), seed=8, now_fn=lambda: NOW).run()
        assert [s.phrase for s in r1.scenes] != [s.phrase for s in r2.scenes]

    def test_dreamed_events_promoted(self):
        reel = REMCycle(a_day(), seed=7, now_fn=lambda: NOW).run(sweeps=3)
        assert reel.scenes
        for key, count in reel.dream_counts.items():
            assert reel.deltas[key] == pytest.approx(
                min(BIAS_MAX, 0.10 * count))

    def test_quiet_low_salience_demoted(self):
        # a day big enough that something is left undreamed
        events = [(h, "memory", f"unremarkable moment number {h}",
                   0.31, None) for h in range(1, 20)]
        events.append((12, "promise", "send Marcus the contract", 0.9, None))
        reel = REMCycle(ring_with(events), seed=3,
                        now_fn=lambda: NOW).run(sweeps=1)
        demoted = [k for k, v in reel.deltas.items() if v < 0]
        assert demoted, "an ignorable day must shed something"
        for key in demoted:
            assert reel.dream_counts.get(key, 0) == 0

    def test_deltas_bounded(self):
        reel = REMCycle(a_day(), seed=7, now_fn=lambda: NOW).run(sweeps=50)
        assert all(-BIAS_MAX <= v <= BIAS_MAX for v in reel.deltas.values())

    def test_promises_dream_loudest(self):
        counts = {"promise": 0, "memory": 0}
        for seed in range(12):
            reel = REMCycle(a_day(), seed=seed, now_fn=lambda: NOW).run()
            for s in reel.scenes:
                for key in (s.a_key, s.b_key):
                    summ = reel.summaries[key]
                    if "contract by Friday" in summ:
                        counts["promise"] += 1
                    if "watered the plants" in summ:
                        counts["memory"] += 1
        assert counts["promise"] > counts["memory"]

    def test_private_events_never_dreamed(self):
        ring = a_day()
        ring.append(MemoryEvent(kind="memory",
                                summary="private therapy note",
                                confidence=0.95, meta={"private": True}),
                    ts=NOW - 3 * H)
        reel = REMCycle(ring, seed=7, now_fn=lambda: NOW).run(sweeps=10)
        assert all("therapy" not in s.phrase for s in reel.scenes)
        assert event_key("memory", "private therapy note") not in reel.deltas

    def test_cross_hour_recombination_bias(self):
        reel = REMCycle(a_day(), seed=7, now_fn=lambda: NOW).run(sweeps=5)
        cross = sum(1 for s in reel.scenes if s.a_hour != s.b_hour)
        assert cross >= len(reel.scenes) * 0.8

    def test_empty_day_dreams_nothing(self):
        reel = REMCycle(ring_with([]), seed=7, now_fn=lambda: NOW).run()
        assert reel.scenes == [] and reel.deltas == {}


class TestPoet:
    def test_words_trace_to_sources(self):
        import random
        poet = DreamPoet(random.Random(5))
        a = "keys on the kitchen counter"
        b = "rolled with Dre at the gym"
        phrase = poet.weave(a, b)
        content = [w.strip(",.'") for w in phrase.split()
                   if w not in ("the", "a", "in", "at", "of", "is",
                                "but", "made", "under", "hour",
                                "remembers", "waiting", "watching")]
        source_words = set((a + " " + b).lower().split()) | {"gym", "kitchen"}
        for word in content:
            assert any(word in sw or sw in word for sw in source_words), \
                f"{word!r} appears from nowhere"

    def test_hud_discipline(self):
        import random
        poet = DreamPoet(random.Random(1))
        for _ in range(30):
            phrase = poet.weave("met Maya about the contract deadline",
                                "a grey cat on the studio windowsill")
            assert len(phrase.split()) <= 8


class TestBias:
    def test_roundtrip(self, tmp_path):
        b = RetrievalBias()
        b.apply({"k1": 0.3, "k2": -0.2})
        b.save(tmp_path)
        loaded = RetrievalBias.load(tmp_path)
        assert loaded.get("k1") == pytest.approx(0.3)
        assert loaded.get("k2") == pytest.approx(-0.2)

    def test_clamped(self):
        b = RetrievalBias()
        for _ in range(10):
            b.apply({"k": 0.4})
        assert b.get("k") == BIAS_MAX

    def test_decay_forgets(self):
        b = RetrievalBias({"old": 0.02})
        b.decay()
        assert b.get("old") == 0.0

    def test_nightly_application_decays_previous(self):
        bias = RetrievalBias({"stale": 0.4})
        reel = REMCycle(a_day(), seed=7, now_fn=lambda: NOW).run()
        reel.apply_to(bias)
        assert bias.get("stale") == pytest.approx(0.2)


class TestMorningHorizon:
    def test_dreamed_marks_wake_brighter(self):
        ring = a_day()
        reel = REMCycle(ring, seed=7, now_fn=lambda: NOW).run(sweeps=3)
        bias = reel.apply_to(RetrievalBias())
        plain = HorizonComposer(ring, None, now_fn=lambda: NOW).compose(NOW)
        dreamt = HorizonComposer(ring, None, now_fn=lambda: NOW,
                                 rem=bias).compose(NOW)
        codes0, codes1 = plain["v"][1::2], dreamt["v"][1::2]
        assert len(codes0) == len(codes1)
        assert any(b > a for a, b in zip(codes0, codes1)), \
            "the night must leave a visible trace"
        assert all(b >= a for a, b in zip(codes0, codes1))
        # luma never exceeds the tier ceiling
        assert all(code % 10 <= 2 for code in codes1)

    def test_no_bias_no_change(self):
        ring = a_day()
        plain = HorizonComposer(ring, None, now_fn=lambda: NOW).compose(NOW)
        rem0 = HorizonComposer(ring, None, now_fn=lambda: NOW,
                               rem=RetrievalBias()).compose(NOW)
        assert plain["v"] == rem0["v"]


class TestReel:
    def test_reel_renders_and_reports(self, tmp_path):
        reel = REMCycle(a_day(), seed=7, now_fn=lambda: NOW).run()
        written = render_reel(reel, tmp_path)
        assert (tmp_path / "reel.txt").exists()
        report = (tmp_path / "reel.txt").read_text()
        assert "consolidated" in report
        if written:                      # Pillow present
            from PIL import Image
            img = Image.open(written[0])
            assert img.size == (256, 256)
            assert img.getbbox() is not None   # never a black frame


class TestForgetReachesTheBias:
    """Audit 2026-07-14 HIGH: forget-that / erase-everything must drop the REM
    consolidation opinion too, or a forgotten memory leaves a content-hash
    fingerprint + a rank-ghost in rem_bias.json."""

    def _retriever_with_bias(self, tmp_path):
        from dreamlayer.memory.db import MemoryDB
        from dreamlayer.memory.retrieval import Retriever
        from dreamlayer.rem.bias import RetrievalBias, event_key
        db = MemoryDB(":memory:")
        bias = RetrievalBias()
        r = Retriever(db, bias_store=bias, bias_dir=str(tmp_path))
        return db, bias, r, event_key

    def test_purge_memory_discards_the_bias(self, tmp_path):
        db, bias, r, event_key = self._retriever_with_bias(tmp_path)
        mid = db.add_memory("object", "the red bike by the north rack", 0.8)
        bias.apply({event_key("object", "the red bike by the north rack"): 0.4})
        assert bias.boost_for("object", "the red bike by the north rack") == 0.4
        r.purge_memory(mid)
        assert bias.boost_for("object", "the red bike by the north rack") == 0.0
        assert len(bias) == 0
        # persisted, so a restart cannot resurrect the fingerprint
        from dreamlayer.rem.bias import RetrievalBias
        assert len(RetrievalBias.load(str(tmp_path))) == 0

    def test_purge_all_clears_the_bias(self, tmp_path):
        db, bias, r, event_key = self._retriever_with_bias(tmp_path)
        db.add_memory("object", "keys on the hook", 0.8)
        bias.apply({event_key("object", "keys on the hook"): 0.3,
                    event_key("promise", "lease by friday"): -0.2})
        assert len(bias) == 2
        r.purge_all()
        assert len(bias) == 0
        from dreamlayer.rem.bias import RetrievalBias
        assert len(RetrievalBias.load(str(tmp_path))) == 0


class TestNightWatchCrashConsistency:
    """A crashed night must never double-consolidate (audit 2026-07-14: the
    bias/stamp pair was written bias-first and non-atomically, so a crash
    between the two writes left should_run eligible and the next run re-applied
    the same deltas onto the already-updated bias)."""

    def _night_ts(self):
        import time as _t
        # 23:00 local on an arbitrary day — inside the NIGHT_FROM..NIGHT_UNTIL
        # window whatever the timezone-independent hour check sees.
        return _t.mktime((2023, 11, 14, 23, 0, 0, 0, 0, -1))

    def test_stamp_lands_before_the_bias_write(self, tmp_path, monkeypatch):
        # SECURITY-ADJACENT (revert-failing): crash bias.save mid-night; the
        # cooldown stamp must ALREADY be durable, so the interrupted night can
        # never be re-run inside the gap and re-apply its deltas. Under the
        # old bias-first order the stamp is missing here and this fails.
        from dreamlayer.rem.nightly import NightWatch

        night = self._night_ts()
        watch = NightWatch(tmp_path, now_fn=lambda: night)

        def boom(self, directory):
            raise OSError("disk died mid-night")
        monkeypatch.setattr(RetrievalBias, "save", boom)

        with pytest.raises(OSError):
            watch.run(a_day(), now=night)

        assert watch.last_night() == night          # stamp survived the crash
        assert not (tmp_path / "rem_bias.json").exists()  # deltas 0×, never 2×
        # and the cooldown now holds: the interrupted night cannot re-run
        assert watch.should_run(charging=True, now=night + 60.0) is False

    def test_clean_night_leaves_no_tmp_residue(self, tmp_path):
        from dreamlayer.rem.nightly import NightWatch

        night = self._night_ts()
        watch = NightWatch(tmp_path, now_fn=lambda: night)
        reel = watch.run(a_day(), now=night)
        assert reel.scenes
        # both writes are tmp+os.replace atomic: files parse, no .tmp left
        import json as _json
        assert _json.loads((tmp_path / "rem_last_night.json").read_text())["ts"] == night
        assert _json.loads((tmp_path / "rem_bias.json").read_text())
        assert not list(tmp_path.glob("*.tmp"))

    def test_corrupt_stamp_recovers_and_warns(self, tmp_path, caplog):
        from dreamlayer.rem.nightly import NightWatch

        (tmp_path / "rem_last_night.json").write_text("{torn")
        watch = NightWatch(tmp_path)
        import logging as _logging
        with caplog.at_level(_logging.WARNING, logger="dreamlayer.rem.nightly"):
            assert watch.last_night() == 0.0
        assert any("unreadable night stamp" in r.message for r in caplog.records)
