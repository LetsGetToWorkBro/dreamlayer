"""Tests for DreamEngine lifecycle and sensor feed."""
import asyncio

import pytest

from dreamlayer.dream_mode.engine import DreamEngine
from dreamlayer.dream_mode.mic_reactor import MicReactor
from dreamlayer.dream_mode.scene_describer import SceneDescriber
from dreamlayer.orchestrator.recall_context import RecallContext


class FakeBridge:
    def __init__(self):
        self.raw_sent = []
        self.cards_sent = []
    def send_raw(self, cmd): self.raw_sent.append(cmd)
    def send_card(self, card, event=None): self.cards_sent.append((card, event))


class _Gate:
    """Minimal privacy stub mirroring PrivacyGate.allow_capture()."""
    def __init__(self, allow: bool): self._allow = allow
    def allow_capture(self) -> bool: return self._allow


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


# ---------------------------------------------------------------------------
# Finding #1 (audit CRITICAL #2): the two capture primitives (camera→VLM,
# mic→palette) must refuse at their OWN tick when the veil is up — the raw
# frame must never reach the VLM while veiled/incognito, even via a direct
# caller that bypasses DreamEngine._tick's staged-frame drop.
# ---------------------------------------------------------------------------

def _camera_ctx(jpeg=b"\xff\xd8\xff raw"):
    ctx = RecallContext()
    ctx.camera_frame = jpeg
    return ctx


def _mic_ctx():
    ctx = RecallContext()
    ctx.mic_fft = [0.8] * 32
    ctx.mic_amplitude = 0.9
    return ctx


def test_scene_describer_veiled_makes_zero_vlm_calls():
    """REVERT-FAILING: a paused/incognito gate suppresses the VLM entirely —
    the raw camera JPEG never reaches _vision_fn and tick() returns None. Revert
    the in-primitive gate and the veiled call proceeds to the VLM, breaking both
    asserts."""
    calls = []

    async def vision(jpeg, prompt):
        calls.append(prompt)
        return "a glimpse it must never take"

    sd = SceneDescriber(vision_fn=vision, privacy=_Gate(False))
    assert asyncio.run(sd.tick(_camera_ctx())) is None
    assert calls == []                      # zero VLM calls while veiled


def test_scene_describer_open_gate_reaches_vlm():
    """Positive control: an OPEN gate still reaches the VLM, so the deny above
    is not vacuous."""
    calls = []

    async def vision(jpeg, prompt):
        calls.append(prompt)
        return "warm cafe hum cups and patience"

    sd = SceneDescriber(vision_fn=vision, privacy=_Gate(True))
    card = asyncio.run(sd.tick(_camera_ctx()))
    assert card is not None
    assert calls                            # the VLM was actually called


def test_mic_reactor_veiled_emits_no_palette_frame():
    """REVERT-FAILING: veiled mic tick yields no palette-weather frame; an open
    gate (control) still does."""
    assert MicReactor(privacy=_Gate(False)).tick(_mic_ctx()) is None
    assert MicReactor(privacy=_Gate(True)).tick(_mic_ctx()) is not None


def test_engine_injects_real_gate_into_capture_primitives():
    """Non-vacuous wiring: the gate reaching describer/mic is the SAME object
    the Orchestrator injected into DreamEngine — not a permissive default."""
    gate = _Gate(False)
    engine = DreamEngine(bridge=FakeBridge(), privacy=gate)
    assert engine.describer._privacy is gate
    assert engine.mic._privacy is gate


def test_engine_tick_sends_no_scene_card_while_veiled():
    """Engine hot path: with a paused gate, a pre-veil staged frame is dropped
    and the describer is never asked for a card (defense in depth over the
    primitive refusal)."""
    calls = []

    async def vision(jpeg, prompt):
        calls.append(prompt)
        return "should never render"

    engine = DreamEngine(bridge=FakeBridge(), privacy=_Gate(False))
    engine.describer.set_vision_fn(vision)
    engine._ctx.camera_frame = b"\xff\xd8\xff staged-before-veil"
    engine._last_scene_t = -1e9             # force the scene interval open
    asyncio.run(engine._tick())
    assert calls == []
    assert engine._ctx.camera_frame is None  # residue dropped


def test_feed_bridges_sync_start_to_async_loop():
    """REVERT-FAILING (_ensure_task was dead code): start() outside a running
    loop leaves _task None; the first sensor feed that arrives inside a loop must
    schedule the ambient loop. Without the feed→_ensure_task wiring the loop
    never starts and _task stays None."""
    engine, _ = make_engine()
    engine.start()                          # sync context: no running loop
    assert engine.running and engine._task is None

    async def drive():
        engine.feed_imu({"yaw": 1.0}, {})   # now inside a running loop
        t = engine._task
        engine.stop()                       # cancel before the loop closes
        if t is not None:
            try:
                await t
            except asyncio.CancelledError:
                pass
        return t

    assert asyncio.run(drive()) is not None
