"""Integration tests for Orchestrator Dream Mode wiring.

All tests are synchronous.  DreamEngine.start() no longer raises
RuntimeError when called outside an event loop (fixed in engine.py).
The loop task is simply not scheduled in sync context, but all state
transitions, BLE sends, and sensor feed-through are fully testable.
"""
import pytest
from memoscape.app.orchestrator import Orchestrator


class FakeBridge:
    def __init__(self):
        self.raw_sent = []
        self.cards = []
        self.commands = []
        self.events = []
        self._event_handler = None

    def on_event(self, fn):
        self._event_handler = fn

    def fire(self, name, payload=None):
        self._event_handler(name, payload or {})

    def send_raw(self, cmd):
        self.raw_sent.append(cmd)

    def send_card(self, card, event=None):
        self.cards.append((card, event))

    def send_command(self, cmd):
        self.commands.append(cmd)

    def inject_event(self, name):
        self.events.append(name)


def make_orc():
    bridge = FakeBridge()
    orc = Orchestrator(bridge)
    return orc, bridge


# ------------------------------------------------------------------
# State transitions
# ------------------------------------------------------------------

def test_double_tap_enters_dream():
    orc, bridge = make_orc()
    bridge.fire("double_tap")
    assert orc.state.is_dream()


def test_double_tap_again_exits_dream():
    orc, bridge = make_orc()
    bridge.fire("double_tap")   # enter
    bridge.fire("double_tap")   # exit
    assert not orc.state.is_dream()


def test_enter_dream_sends_ble_command():
    orc, bridge = make_orc()
    orc.enter_dream()
    raw_types = [r.get("t") for r in bridge.raw_sent]
    assert "dream_enter" in raw_types


def test_exit_dream_sends_ble_command_and_ready():
    orc, bridge = make_orc()
    orc.enter_dream()
    bridge.raw_sent.clear()
    bridge.commands.clear()
    orc.exit_dream()
    raw_types = [r.get("t") for r in bridge.raw_sent]
    assert "dream_exit" in raw_types
    assert "show_ready" in bridge.commands


# ------------------------------------------------------------------
# Sensor feed-through
# ------------------------------------------------------------------

def test_on_audio_frame_feeds_mic_in_dream_mode():
    orc, bridge = make_orc()
    orc.enter_dream()
    orc.on_audio_frame("", context={"mic_fft": [0.5] * 32, "mic_amplitude": 0.7})
    assert orc.dream._ctx.mic_fft == [0.5] * 32
    assert orc.dream._ctx.mic_amplitude == pytest.approx(0.7)


def test_on_scene_frame_feeds_camera_in_dream_mode():
    orc, _ = make_orc()
    orc.enter_dream()
    jpeg = b"\xff\xd8\xff"
    orc.on_scene_frame({"camera_jpeg": jpeg, "imu_pose": {}})
    assert orc.dream._ctx.camera_frame == jpeg


def test_on_scene_frame_feeds_imu_in_dream_mode():
    orc, _ = make_orc()
    orc.enter_dream()
    pose = {"pitch": 1.0, "yaw": 2.0, "roll": 0.0}
    delta = {"pitch": 0.1, "yaw": 5.0}
    orc.on_scene_frame({"imu_pose": pose, "imu_delta": delta})
    assert orc.dream._ctx.imu_pose == pose
    assert orc.dream._ctx.imu_delta == delta


def test_on_place_feeds_ghost_layer_in_dream_mode():
    orc, _ = make_orc()
    orc.enter_dream()
    orc.on_place("kitchen_001")
    assert orc.dream._ctx.place_signature == "kitchen_001"


def test_audio_frame_not_fed_outside_dream():
    orc, _ = make_orc()
    orc.on_audio_frame("", context={"mic_fft": [1.0] * 32, "mic_amplitude": 1.0})
    assert orc.dream._ctx.mic_fft is None


# ------------------------------------------------------------------
# Privacy interaction
# ------------------------------------------------------------------

def test_long_press_pauses_in_dream_mode():
    orc, bridge = make_orc()
    orc.enter_dream()
    bridge.fire("long_press")
    assert orc.privacy.paused


# ------------------------------------------------------------------
# Dream engine state
# ------------------------------------------------------------------

def test_dream_engine_running_after_enter():
    orc, _ = make_orc()
    orc.enter_dream()
    assert orc.dream.running is True


def test_dream_engine_stopped_after_exit():
    orc, _ = make_orc()
    orc.enter_dream()
    orc.exit_dream()
    assert orc.dream.running is False
