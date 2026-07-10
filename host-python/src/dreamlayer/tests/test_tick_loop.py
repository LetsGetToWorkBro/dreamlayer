"""test_tick_loop.py — the proactive heartbeat that drives everything.

One tick over a live Context surfaces anticipation cards and lets Juno speak
up; start_ticking() runs it on an interval off a device-seam context function.
"""
from __future__ import annotations

import threading
import time

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.orchestrator.anticipation import Context, Event, Commitment
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _cards(br):
    return [f for f in br.raw if f.get("t") == "card"]


def test_tick_runs_anticipation_and_attention():
    br = FakeBridge()
    orc = Orchestrator(br)
    ctx = Context(now=1000.0, person="Marcus",
                  events=[Event("Standup", ts=1000.0 + 5 * 60)],
                  commitments=[Commitment("Marcus", "the signed lease")])
    out = orc.pulse(ctx)
    assert out["cues"]                                   # anticipation fired a card
    assert out["alert"] and out["alert"]["type"] == "HarkCard"   # Juno spoke up
    kinds = {c["type"] for c in _cards(br)}
    assert "HarkCard" in kinds


def test_tick_quiet_moment_is_silent():
    orc = Orchestrator(FakeBridge())
    out = orc.pulse(Context(now=1000.0))                  # nothing going on
    assert out["cues"] == [] and out["alert"] is None


def test_start_ticking_drives_the_seam_then_stops():
    orc = Orchestrator(FakeBridge())
    calls = {"n": 0}
    fired = threading.Event()

    def context_fn():
        calls["n"] += 1
        fired.set()
        # an event 4 min out → a watch-out every loop (deduped after the first)
        return Context(now=time.time(), events=[Event("gate", ts=time.time() + 240)])

    orc.start_pulse(context_fn, interval=0.02)
    assert fired.wait(2.0)                                # the loop called the seam
    orc.stop_pulse()
    n = calls["n"]
    time.sleep(0.1)
    assert calls["n"] - n <= 1                            # stopped (no more calls)


def test_start_ticking_is_idempotent():
    orc = Orchestrator(FakeBridge())
    orc.start_pulse(lambda: None, interval=5)
    first = orc._tick_stop
    orc.start_pulse(lambda: None, interval=5)           # a second call is a no-op
    assert orc._tick_stop is first
    orc.stop_pulse()
    assert orc._tick_stop is None
