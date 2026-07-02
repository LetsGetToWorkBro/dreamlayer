"""Premonition — future ghosts, precision-gated: the two-Tuesdays law."""
import time
from pathlib import Path

import pytest

from dreamlayer.dream_mode.premonition import (
    RecurrenceModel, CONFIRM_TOL_S, MIN_DAYS,
)
from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.orchestrator.horizon_composer import (
    HorizonComposer, KIND_PREMONITION, MARKS_MAX,
)
from dreamlayer.pipelines.ingest import MemoryEvent

DAY = 86400.0
H = 3600.0

# anchor on a known Tuesday 12:00 UTC (1_700_000_000 ≈ Tue 2023-11-14)
BASE = 1_700_000_000.0
assert time.gmtime(BASE).tm_wday == 1   # Tuesday


def tuesday(weeks_ago: int, hour: int) -> float:
    day = BASE - weeks_ago * 7 * DAY
    start = day - (time.gmtime(day).tm_hour * H
                   + time.gmtime(day).tm_min * 60
                   + time.gmtime(day).tm_sec)
    return start + hour * H


class TestTwoTuesdays:
    """The one test the paradigm lives or dies on: two weeks of logs with
    a Tuesday rhythm, heavy noise, and a one-off decoy must produce
    exactly the rhythm — zero false positives."""

    def make(self) -> RecurrenceModel:
        model = RecurrenceModel(now_fn=lambda: BASE)
        # the rhythm: gym rounds, two consecutive Tuesdays at 18:00
        for weeks in (1, 2):
            model.observe("memory", "rolled rounds at the gym",
                          tuesday(weeks, 18), place="gym")
        # heavy unrelated noise: one-off events all over the fortnight
        for d in range(1, 14):
            model.observe("memory", f"random errand number {d}",
                          BASE - d * DAY + (d % 12) * H)
        # the decoy: looks like a rhythm but happened exactly once
        model.observe("memory", "dentist appointment downtown",
                      tuesday(1, 15), place="dentist")
        return model

    def test_exactly_one_prediction(self):
        model = self.make()
        preds = model.predict(now=tuesday(0, 14))   # Tuesday 14:00
        assert len(preds) == 1
        assert preds[0].slot[3] == "rolled"
        assert preds[0].hour == 18
        assert preds[0].place == "gym"

    def test_decoy_and_noise_never_predict(self):
        model = self.make()
        for probe_hour in range(0, 24, 2):
            for pred in model.predict(now=tuesday(0, probe_hour)):
                assert "dentist" not in pred.slot[3]
                assert "errand" not in pred.slot[3]

    def test_wrong_weekday_stays_dark(self):
        model = self.make()
        wednesday_2pm = tuesday(0, 14) + DAY
        assert model.predict(now=wednesday_2pm) == []

    def test_outside_lookahead_stays_dark(self):
        model = self.make()
        assert model.predict(now=tuesday(0, 8)) == []   # 10h early


class TestConfirmAndDissolve:
    def rhythm(self) -> RecurrenceModel:
        model = RecurrenceModel(now_fn=lambda: BASE)
        for weeks in (1, 2):
            model.observe("memory", "rolled rounds at the gym",
                          tuesday(weeks, 18), place="gym")
        return model

    def test_confirmation_hardens_and_retires_the_ghost(self):
        model = self.rhythm()
        model.predict(now=tuesday(0, 14))
        assert len(model.pending()) == 1
        hit = model.confirm("memory", "rolled rounds at the gym",
                            tuesday(0, 18) + 600, place="gym")
        assert hit
        assert model.pending() == []          # the real mark takes over
        preds = model.predict(now=tuesday(-1, 14))   # next Tuesday
        assert preds and preds[0].confidence > 0.5

    def test_defiance_dissolves_the_slot(self):
        model = self.rhythm()
        # two Tuesdays in a row the ghost shimmers and nothing happens
        for weeks_ahead in (0, -1):
            model.predict(now=tuesday(weeks_ahead, 14))
            model._expire(tuesday(weeks_ahead, 20))   # hour passed, no event
        assert model.predict(now=tuesday(-2, 14)) == []   # gone quiet

    def test_unmatched_event_is_not_a_hit(self):
        model = self.rhythm()
        model.predict(now=tuesday(0, 14))
        hit = model.confirm("memory", "completely different thing",
                            tuesday(0, 18), place="office")
        assert not hit
        assert len(model.pending()) == 1

    def test_private_events_never_observed(self):
        ring = SemanticRingBuffer(capacity=8)
        ring.append(MemoryEvent(kind="memory", summary="secret meeting",
                                confidence=0.9, meta={"private": True}),
                    ts=tuesday(1, 18))
        ring.append(MemoryEvent(kind="memory", summary="secret meeting",
                                confidence=0.9, meta={"private": True}),
                    ts=tuesday(2, 18))
        model = RecurrenceModel(now_fn=lambda: BASE)
        model.observe_buffer(ring)
        assert model.predict(now=tuesday(0, 14)) == []


class TestHorizonGhosts:
    def composer_with_rhythm(self):
        model = RecurrenceModel(now_fn=lambda: BASE)
        for weeks in (1, 2):
            model.observe("memory", "rolled rounds at the gym",
                          tuesday(weeks, 18), place="gym")
        ring = SemanticRingBuffer(capacity=8)
        now = tuesday(0, 14)
        return HorizonComposer(ring, None, now_fn=lambda: now,
                               premonition=model), now

    def test_future_ghost_on_the_future_side(self):
        composer, now = self.composer_with_rhythm()
        frame = composer.compose(now)
        codes = frame["v"][1::2]
        degs = frame["v"][0::2]
        ghosts = [(d, c) for d, c in zip(degs, codes)
                  if c // 100 == KIND_PREMONITION]
        assert len(ghosts) == 1
        deg, code = ghosts[0]
        assert code == KIND_PREMONITION * 100 + 1     # always faint
        assert deg == -2100                           # 4h ahead: -90-120°

    def test_ghosts_never_displace_real_marks(self):
        model = RecurrenceModel(now_fn=lambda: BASE)
        for weeks in (1, 2):
            model.observe("memory", "rolled rounds at the gym",
                          tuesday(weeks, 18), place="gym")
        ring = SemanticRingBuffer(capacity=64)
        now = tuesday(0, 14)
        for i in range(60):                            # a saturated day
            ring.append(MemoryEvent(kind="memory",
                                    summary=f"busy moment {i}",
                                    confidence=0.9),
                        ts=now - (i % 4) * H)
        composer = HorizonComposer(ring, None, now_fn=lambda: now,
                                   premonition=model)
        frame = composer.compose(now)
        codes = frame["v"][1::2]
        assert len(codes) <= MARKS_MAX
        assert all(c // 100 != KIND_PREMONITION for c in codes), \
            "a full dial has no spare capacity for ghosts"

    def test_no_model_no_change(self):
        ring = SemanticRingBuffer(capacity=8)
        now = tuesday(0, 14)
        a = HorizonComposer(ring, None, now_fn=lambda: now).compose(now)
        b = HorizonComposer(ring, None, now_fn=lambda: now,
                            premonition=None).compose(now)
        assert a["v"] == b["v"]


class TestDevicePlotter:
    @pytest.fixture
    def horizon(self):
        lupa = pytest.importorskip("lupa")
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        root = Path(__file__).resolve().parents[4] / "halo-lua"
        rt.execute(f'package.path = "{root}/?.lua;" .. package.path')
        hz = rt.eval('require("display.horizon")')
        hz = hz[0] if isinstance(hz, tuple) else hz
        hz.reset()
        return rt, hz

    def test_kind6_admitted_and_drawn(self, horizon):
        rt, hz = horizon
        frame = rt.table(t="horizon", seq=1, paused=0,
                         v=rt.table(-2100, 601))
        assert hz.on_frame(frame, 0)
        marks = hz.marks()
        assert marks[1]["kind"] == 6 and marks[1]["luma"] == 1
        hz.draw(rt.table(now_ms=500))                  # shimmer pass
        hz.draw(rt.table(now_ms=500, reduce_motion=True))

    def test_kind7_still_rejected(self, horizon):
        rt, hz = horizon
        bad = rt.table(t="horizon", seq=2, paused=0,
                       v=rt.table(-2100, 701))
        assert not hz.on_frame(bad, 0)
