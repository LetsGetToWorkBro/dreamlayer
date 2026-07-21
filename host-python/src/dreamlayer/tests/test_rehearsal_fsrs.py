"""memory/rehearsal_fsrs.py — FSRS-scheduled rehearsal (never forget a name).

py-fsrs isn't in CI, so the deterministic baseline carries the tests: interval
growth per rating, the ten-minute first review, due ordering, persistence, and
the never-raise contract. The FSRS engine is pinned to its fallback shape.
"""
from __future__ import annotations

from dreamlayer.memory.rehearsal_fsrs import (
    FsrsEngine, RehearsalScheduler, _baseline_next, default_rehearsal,
)


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _sched(tmp_path, clock=None):
    return RehearsalScheduler(tmp_path / "r.json", now_fn=clock or FakeClock())


class TestBaselineMath:
    def test_good_doubles_with_a_one_day_floor(self):
        assert _baseline_next(0.007, "good") == 1.0
        assert _baseline_next(4.0, "good") == 8.0

    def test_again_resets_to_ten_minutes(self):
        assert abs(_baseline_next(30.0, "again") - 10.0 / 1440.0) < 1e-9

    def test_hard_holds_easy_grows(self):
        assert _baseline_next(4.0, "hard") == 4.0
        assert _baseline_next(4.0, "easy") == 10.0


class TestScheduler:
    def test_add_first_review_in_ten_minutes(self, tmp_path):
        clock = FakeClock()
        s = _sched(tmp_path, clock)
        it = s.add("p:sam", "person", "Sam — met at the gallery")
        assert it is not None
        assert abs(it["due_ts"] - (clock.t + 600.0)) < 1.0

    def test_review_advances_and_due_surfaces_overdue_first(self, tmp_path):
        clock = FakeClock()
        s = _sched(tmp_path, clock)
        s.add("a", "fact", "A")
        s.add("b", "fact", "B")
        clock.t += 700                      # both overdue now
        s.review("a", "good")               # a is rescheduled ~1 day out
        due = s.due()
        assert [d["id"] for d in due] == ["b"]
        clock.t += 2 * 86400
        ids = {d["id"] for d in s.due()}
        assert ids == {"a", "b"}

    def test_persistence_roundtrip(self, tmp_path):
        clock = FakeClock()
        s = _sched(tmp_path, clock)
        s.add("x", "fact", "X")
        s2 = RehearsalScheduler(tmp_path / "r.json", now_fn=clock)
        assert [i["id"] for i in s2.all()] == ["x"]

    def test_corrupt_store_starts_empty_not_crashes(self, tmp_path):
        p = tmp_path / "r.json"
        p.write_text("{not json")
        s = RehearsalScheduler(p, now_fn=FakeClock())
        assert s.all() == []

    def test_junk_inputs_never_raise(self, tmp_path):
        s = _sched(tmp_path)
        assert s.add("", "fact", "text") is None
        assert s.add("id", "fact", "  ") is None
        assert s.review("missing", "good") is None
        assert s.drop("missing") is False
        it = s.add("ok", "fact", "hello")
        assert it is not None
        assert s.review("ok", "not-a-rating") is not None   # falls back to good

    def test_readd_refreshes_text_keeps_schedule(self, tmp_path):
        clock = FakeClock()
        s = _sched(tmp_path, clock)
        first = s.add("p", "person", "Pat")
        clock.t += 50
        second = s.add("p", "person", "Pat — prefers Patricia")
        assert second["due_ts"] == first["due_ts"]
        assert "Patricia" in second["text"]


class TestEngineFallback:
    def test_engine_review_none_without_wheel(self):
        e = FsrsEngine()
        if not FsrsEngine.available:
            assert e.ready is False
            assert e.review(None, "good", 1_000_000.0) is None

    def test_engine_name_reports_honestly(self, tmp_path):
        s = _sched(tmp_path)
        assert s.engine_name in ("fsrs", "baseline")


def test_default_rehearsal_builds(tmp_path):
    s = default_rehearsal(tmp_path)
    assert s.add("n", "person", "Nadia")["reps"] == 0


def test_rehearsal_capability_registered():
    from dreamlayer import capabilities as C
    cap = {c.key: c for c in C.CAPABILITIES}.get("memory_rehearsal")
    assert cap is not None and cap.extra == "srs" and "fsrs" in cap.modules
