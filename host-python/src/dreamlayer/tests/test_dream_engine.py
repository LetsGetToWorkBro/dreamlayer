"""Tests for DreamEngine lifecycle and sensor feed."""
import pytest

from dreamlayer.dream_mode.engine import DreamEngine


class FakeBridge:
    def __init__(self):
        self.raw_sent = []
        self.cards_sent = []
    def send_raw(self, cmd): self.raw_sent.append(cmd)
    def send_card(self, card, event=None): self.cards_sent.append((card, event))


def make_engine():
    bridge = FakeBridge()
    engine = DreamEngine(bridge=bridge)
    return engine, bridge


def test_engine_starts_stopped():
    engine, _ = make_engine()
    assert not engine.running


def test_engine_start_stop():
    engine, _ = make_engine()
    engine.start()
    assert engine.running
    engine.stop()
    assert not engine.running


def test_double_start_is_idempotent():
    engine, _ = make_engine()
    engine.start()
    task1 = engine._task
    engine.start()   # second start should no-op
    assert engine._task is task1
    engine.stop()


def test_feed_mic_updates_context():
    engine, _ = make_engine()
    engine.feed_mic([0.1] * 32, 0.5)
    assert engine._ctx.mic_amplitude == 0.5
    assert len(engine._ctx.mic_fft) == 32


def test_feed_imu_updates_context():
    engine, _ = make_engine()
    engine.feed_imu({"pitch": 1.0, "yaw": 2.0, "roll": 0.0}, {"pitch": 0.1, "yaw": 0.2})
    assert engine._ctx.imu_pose["yaw"] == 2.0
    assert engine._ctx.imu_delta["yaw"] == 0.2


def test_feed_camera_updates_context():
    engine, _ = make_engine()
    engine.feed_camera(b"\xff\xd8\xff")
    assert engine._ctx.camera_frame == b"\xff\xd8\xff"
    assert engine._ctx.has_camera()


def test_feed_place_updates_context():
    engine, _ = make_engine()
    anchors = [{"id": "a1", "summary": "Keys here", "confidence": 0.9}]
    engine.feed_place("gym_001", anchors)
    assert engine._ctx.place_signature == "gym_001"
    assert len(engine._ctx.world_anchors) == 1


@pytest.mark.asyncio
async def test_tick_fires_mic_palette_command():
    engine, bridge = make_engine()
    engine.feed_mic([0.8] * 32, 0.9)
    await engine._tick()
    palette_cmds = [c for c in bridge.raw_sent if c.get("t") == "palette"]
    assert len(palette_cmds) == 1
    assert "colors" in palette_cmds[0]


@pytest.mark.asyncio
async def test_tick_no_commands_without_sensors():
    engine, bridge = make_engine()
    # No sensor data fed — should produce no raw sends
    await engine._tick()
    assert bridge.raw_sent == []
