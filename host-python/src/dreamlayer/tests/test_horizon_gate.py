"""The privacy gate for horizon frames (docs/cinema_v2/horizon_frame.md):
while paused, ONLY the empty pause frame crosses the bridge — a horizon
frame carrying marks is captured signal and never passes. Defense in
depth with the composer's own paused check (two mistakes in two files
required to leak).
"""
from dreamlayer.bridge.base import pause_allows_raw
from dreamlayer.bridge.emulator_bridge import EmulatorBridge


def test_pause_gate_allows_only_the_empty_horizon_frame():
    assert pause_allows_raw({"t": "horizon", "seq": 9, "paused": 1, "v": []})
    assert not pause_allows_raw(
        {"t": "horizon", "seq": 9, "paused": 0, "v": [0, 102]})
    # mode control still passes; signal-bearing frames never do
    assert pause_allows_raw({"t": "dream_enter"})
    assert not pause_allows_raw({"t": "palette", "colors": []})
    assert not pause_allows_raw({"t": "line_field", "v": [1, 2, 3, 4]})


def test_emulator_bridge_enforces_the_gate():
    b = EmulatorBridge()
    b.connect()
    b.inject_event("privacy_pause")
    b.send_raw({"t": "horizon", "seq": 1, "paused": 0, "v": [0, 102]})
    b.send_raw({"t": "horizon", "seq": 2, "paused": 1, "v": []})
    horizon_frames = [f for f in b.raw_frames if f.get("t") == "horizon"]
    assert horizon_frames == [{"t": "horizon", "seq": 2, "paused": 1, "v": []}]


def test_orchestrator_sends_empty_frame_while_paused():
    from dreamlayer.orchestrator.orchestrator import Orchestrator
    o = Orchestrator(EmulatorBridge())
    o.pause()
    frame = o.tick_horizon(now=10_000.0)
    assert frame is not None and frame["paused"] == 1 and frame["v"] == []
