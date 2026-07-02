"""Tests for orchestrator/horizon_composer.py — the Horizon Frame
(docs/cinema_v2/horizon_frame.md): dial geometry, wire format, the
promises-are-never-dropped cap rule, the pause contract, cadence, and
the end-to-end codec into display/horizon.lua through lib/json.
"""
import json
import pathlib

import pytest

from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.orchestrator.commitment_drift import CommitmentDriftEngine
from dreamlayer.orchestrator.horizon_composer import (
    HorizonComposer, NOW_DEG, ELDER_DEG, FUTURE_CAP_DEG, MARKS_MAX,
    KIND_MEMORY, KIND_PROMISE, KIND_PERSON, KIND_ELDER, KIND_FUTURE_CAP,
    CADENCE_S,
)
from dreamlayer.pipelines.ingest import MemoryEvent

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"

NOW = 1_000_000.0


def _ring(events):
    ring = SemanticRingBuffer(capacity=128)
    for kind, conf, ts in events:
        ring.append(MemoryEvent(kind=kind, summary=f"{kind}@{ts}",
                             confidence=conf), ts=ts)
    return ring


def _composer(events=(), drift=None):
    return HorizonComposer(_ring(events), drift, now_fn=lambda: NOW)


def _marks(frame):
    v = frame["v"]
    assert len(v) % 2 == 0
    return [(v[i] / 10.0, v[i + 1]) for i in range(0, len(v), 2)]


# ---------------------------------------------------------------------------
# Dial geometry
# ---------------------------------------------------------------------------

def test_now_is_twelve_oclock_past_sweeps_clockwise():
    c = _composer()
    assert c.angle_for_ts(NOW) == NOW_DEG
    assert c.angle_for_ts(NOW - 3 * 3600) == pytest.approx(0.0)    # 3h ago
    assert c.angle_for_ts(NOW - 1 * 3600) == pytest.approx(-60.0)  # 1h ago


def test_older_than_window_goes_to_the_elder_door():
    c = _composer()
    assert c.angle_for_ts(NOW - 8 * 3600) == ELDER_DEG


def test_memory_marks_encode_kind_and_luma():
    c = _composer([("object", 0.9, NOW - 3600),   # full tier
                   ("object", 0.5, NOW - 7200),   # dim tier
                   ("person", 0.9, NOW - 1800),   # person pin
                   ("object", 0.1, NOW - 600)])   # below floor: dropped
    marks = _marks(c.compose())
    codes = sorted(code for _, code in marks)
    assert codes == [KIND_MEMORY * 100 + 1, KIND_MEMORY * 100 + 2,
                     KIND_PERSON * 100 + 2]


def test_promise_due_times_sit_counterclockwise():
    ring = _ring([("task", 0.8, NOW - 60)])
    drift = CommitmentDriftEngine(ring)

    class Rec:  # minimal drift-record stand-in
        state = "healthy"
        due_ts = NOW + 2 * 3600
        event = type("E", (), {"confidence": 0.8})()

    class Drift:
        def all_records(self):
            return [Rec()]

    c = HorizonComposer(_ring([]), Drift(), now_fn=lambda: NOW)
    marks = _marks(c.compose())
    assert len(marks) == 1
    deg, code = marks[0]
    assert deg == pytest.approx(-150.0)             # -90 - 2h*30°
    assert code // 100 == KIND_PROMISE
    assert (code // 10) % 10 == 2                    # healthy


def test_far_future_promise_collapses_to_the_cap():
    class Rec:
        state = "blooming"
        due_ts = NOW + 9 * 3600
        event = type("E", (), {"confidence": 0.8})()

    class Drift:
        def all_records(self):
            return [Rec()]

    c = HorizonComposer(_ring([]), Drift(), now_fn=lambda: NOW)
    marks = _marks(c.compose())
    assert marks == [(FUTURE_CAP_DEG, KIND_FUTURE_CAP * 100 + 1)]


def test_past_due_promise_crosses_to_the_past_side():
    class Rec:
        state = "shattered"
        due_ts = NOW - 2 * 3600
        event = type("E", (), {"confidence": 0.8})()

    class Drift:
        def all_records(self):
            return [Rec()]

    c = HorizonComposer(_ring([]), Drift(), now_fn=lambda: NOW)
    (deg, code), = _marks(c.compose())
    assert deg == pytest.approx(-30.0)               # 2h ago, past side
    assert (code // 10) % 10 == 5                    # shattered


# ---------------------------------------------------------------------------
# The cap: lowest-confidence memories drop first, promises never
# ---------------------------------------------------------------------------

def test_cap_drops_memories_never_promises():
    events = [("object", 0.3 + (i % 60) * 0.01, NOW - 60 - i * 30)
              for i in range(70)]
    ring = _ring(events)

    class Rec:
        def __init__(self, h):
            self.state = "healthy"
            self.due_ts = NOW + h * 3600
            self.event = type("E", (), {"confidence": 0.9})()

    class Drift:
        def all_records(self):
            return [Rec(1), Rec(2), Rec(3)]

    c = HorizonComposer(ring, Drift(), now_fn=lambda: NOW)
    marks = _marks(c.compose())
    assert len(marks) <= MARKS_MAX + 1               # +1: the elder tick
    promise_marks = [m for m in marks if m[1] // 100 == KIND_PROMISE]
    assert len(promise_marks) == 3                   # never dropped
    assert any(m[1] // 100 == KIND_ELDER for m in marks)  # overflow shown


# ---------------------------------------------------------------------------
# Pause contract + cadence
# ---------------------------------------------------------------------------

def test_paused_frame_is_empty_and_flagged():
    c = _composer([("object", 0.9, NOW - 3600)])
    frame = c.compose(paused=True)
    assert frame["paused"] == 1 and frame["v"] == []


def test_cadence_rate_limits_unchanged_state():
    c = _composer([("object", 0.9, NOW - 3600)])
    t = [NOW]
    c._now = lambda: t[0]
    assert c.maybe_frame() is not None               # first frame flows
    t[0] += 1.0
    assert c.maybe_frame() is None                   # unchanged + not due
    t[0] += CADENCE_S
    assert c.maybe_frame() is not None               # heartbeat


def test_change_bypasses_cadence():
    ring = _ring([("object", 0.9, NOW - 3600)])
    c = HorizonComposer(ring, None, now_fn=lambda: NOW)
    t = [NOW]
    c._now = lambda: t[0]
    assert c.maybe_frame() is not None
    t[0] += 1.0
    ring.append(MemoryEvent(kind="object", summary="new", confidence=0.9),
             ts=t[0])
    assert c.maybe_frame() is not None               # changed state flows


def test_seq_is_monotonic_across_sent_frames():
    c = _composer([("object", 0.9, NOW - 3600)])
    t = [NOW]
    c._now = lambda: t[0]
    f1 = c.maybe_frame()
    t[0] += CADENCE_S + 1
    f2 = c.maybe_frame()
    assert f2["seq"] > f1["seq"]


# ---------------------------------------------------------------------------
# End-to-end codec: composed frame -> JSON -> lib/json -> horizon.lua
# ---------------------------------------------------------------------------

def test_composed_frame_decodes_on_device():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    c = _composer([("object", 0.9, NOW - 3600),
                   ("person", 0.8, NOW - 1800)])
    wire = json.dumps(c.compose(), separators=(",", ":"))

    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("frame = nil")   # codec test: no drawing needed
    rt.execute('_hz = require("display.horizon"); _hz.reset()')
    rt.execute('_json = require("lib.json")')
    rt.globals()["_wire"] = wire
    assert rt.eval("_hz.on_frame(_json.decode(_wire), 1000)")
    marks = rt.eval("_hz.marks()")
    assert len(marks) == 2
    kinds = sorted(marks[i + 1].kind for i in range(2))
    assert kinds == [KIND_MEMORY, KIND_PERSON]
