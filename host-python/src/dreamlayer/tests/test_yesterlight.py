"""Yesterlight — the room's memory of its own light, replayed in place."""
from pathlib import Path

import pytest

from dreamlayer.dream_mode.weather_ledger import (
    WeatherLedger, SNAPSHOT_EVERY_S,
)
from dreamlayer.dream_mode.yesterlight import (
    YesterlightController, scrub_angle, freshness,
    ENTER_PITCH, ENTER_TICKS, EXIT_PITCH, MSG_YESTERLIGHT,
)
from dreamlayer.orchestrator.recall_context import RecallContext

NOW = 1_700_000_000.0
H = 3600.0


def palette(hour: int) -> dict:
    """A distinguishable palette frame per hour."""
    return {"t": "palette",
            "colors": [{"idx": 1, "y": hour, "cb": 128, "cr": 128}]}


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


class Veil:
    def __init__(self, allow=True):
        self.allow = allow

    def allow_capture(self):
        return self.allow


def stocked_ledger(clock, place="kitchen", hours=6) -> WeatherLedger:
    """A ledger with one snapshot per past hour at `place`."""
    ledger = WeatherLedger(now_fn=clock)
    for h in range(hours, 0, -1):
        clock.t = NOW - h * H
        ledger._last_record = 0.0
        assert ledger.record(place, palette(h), amplitude=h / 10)
    clock.t = NOW
    return ledger


class TestLedger:
    def test_record_and_nearest(self):
        clock = Clock()
        ledger = stocked_ledger(clock)
        snap = ledger.nearest("kitchen", NOW - 3 * H)
        assert snap is not None
        assert snap.colors[0]["y"] == 3

    def test_sampling_rate_limited(self):
        clock = Clock()
        ledger = WeatherLedger(now_fn=clock)
        assert ledger.record("kitchen", palette(1))
        clock.t += SNAPSHOT_EVERY_S / 2
        assert not ledger.record("kitchen", palette(2))
        clock.t += SNAPSHOT_EVERY_S
        assert ledger.record("kitchen", palette(3))

    def test_privacy_veil_blocks_recording(self):
        veil = Veil(allow=False)
        ledger = WeatherLedger(privacy=veil, now_fn=Clock())
        assert not ledger.record("kitchen", palette(1))
        assert len(ledger) == 0

    def test_place_isolation(self):
        clock = Clock()
        ledger = stocked_ledger(clock, place="kitchen")
        assert ledger.nearest("gym", NOW - 3 * H) is None
        assert ledger.span("gym") is None

    def test_tolerance(self):
        clock = Clock()
        ledger = stocked_ledger(clock)
        assert ledger.nearest("kitchen", NOW - 40 * H) is None

    def test_persistence_roundtrip(self, tmp_path):
        clock = Clock()
        ledger = stocked_ledger(clock)
        path = ledger.save(tmp_path / "weather.jsonl")
        loaded = WeatherLedger.load(path)
        assert len(loaded) == len(ledger)
        assert loaded.nearest("kitchen", NOW - 2 * H).colors[0]["y"] == 2


def ctx(pitch=0.0, place="kitchen", anchors=None) -> RecallContext:
    return RecallContext(imu_pose={"pitch": pitch, "yaw": 0, "roll": 0},
                         place_signature=place,
                         world_anchors=anchors or [])


def hold(controller, pitch, place="kitchen", ticks=ENTER_TICKS):
    frames = []
    for _ in range(ticks):
        frames = controller.tick(ctx(pitch=pitch, place=place))
    return frames


class TestController:
    def make(self):
        clock = Clock()
        ledger = stocked_ledger(clock)
        return YesterlightController(ledger, now_fn=clock), clock

    def test_glance_does_not_enter(self):
        yl, _ = self.make()
        yl.tick(ctx(pitch=-0.9))                # one glance up
        yl.tick(ctx(pitch=0.0))
        assert not yl.active

    def test_deliberate_hold_enters_and_replays(self):
        yl, _ = self.make()
        frames = hold(yl, pitch=-0.8)
        assert yl.active
        frames = yl.tick(ctx(pitch=-0.8))
        types = [f["t"] for f in frames]
        assert types == ["palette", MSG_YESTERLIGHT]
        assert frames[1]["active"] == 1
        assert "notch_dd" in frames[1]
        # the palette is history, verbatim
        assert frames[0]["colors"][0]["y"] in range(1, 7)

    def test_deeper_tilt_scrubs_further_back(self):
        yl, _ = self.make()
        hold(yl, pitch=-0.6)
        shallow = yl.tick(ctx(pitch=-0.6))[0]["colors"][0]["y"]
        deep = yl.tick(ctx(pitch=-1.4))[0]["colors"][0]["y"]
        assert deep > shallow        # older hour = larger y in our fixture

    def test_head_return_exits_with_release_frame(self):
        yl, _ = self.make()
        hold(yl, pitch=-0.8)
        yl.tick(ctx(pitch=-0.8))
        frames = yl.tick(ctx(pitch=0.0))
        assert frames == [{"t": MSG_YESTERLIGHT, "active": 0}]
        assert not yl.active

    def test_place_change_exits(self):
        yl, _ = self.make()
        hold(yl, pitch=-0.8)
        yl.tick(ctx(pitch=-0.8))
        frames = yl.tick(ctx(pitch=-0.8, place="gym"))
        assert frames == [{"t": MSG_YESTERLIGHT, "active": 0}]

    def test_no_history_no_entry(self):
        clock = Clock()
        yl = YesterlightController(WeatherLedger(now_fn=clock),
                                   now_fn=clock)
        hold(yl, pitch=-0.9)
        assert not yl.active

    def test_anchor_echo_at_visited_hour(self):
        yl, _ = self.make()
        anchors = [{"summary": "keys here", "ts": NOW - 2 * H}]
        for _ in range(ENTER_TICKS):
            yl.tick(ctx(pitch=-0.85, anchors=anchors))
        # depth ≈0.30 rad → ≈72 min back; widen until the echo hour is hit
        frames = yl.tick(ctx(pitch=-1.05, anchors=anchors))
        state = frames[1]
        assert "echo_dd" in state
        assert state["echo_dd"] == pytest.approx(
            round(scrub_angle(120) * 10), abs=20)

    def test_timeout_exits(self):
        yl, clock = self.make()
        hold(yl, pitch=-0.8)
        yl.tick(ctx(pitch=-0.8))
        clock.t += 200.0
        frames = yl.tick(ctx(pitch=-0.8))
        assert frames == [{"t": MSG_YESTERLIGHT, "active": 0}]


class TestGeometry:
    def test_scrub_angle_matches_dial_law(self):
        assert scrub_angle(0) == -90.0
        assert scrub_angle(60) == -60.0          # one hour = 30°
        assert scrub_angle(600) == 58.0          # clamped at the elder door

    def test_freshness_bounds(self):
        assert freshness(0) == 1.0
        assert freshness(86400) == pytest.approx(0.35)
        assert freshness(10 * 86400) == 0.35


class TestDevicePlotter:
    """The Lua horizon draws the detached notch (lupa)."""

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

    def test_scrub_state_set_and_cleared(self, horizon):
        rt, hz = horizon
        on = rt.table(t=MSG_YESTERLIGHT, active=1, notch_dd=-300)
        hz.on_yesterlight(on, 0)
        scrub = hz.scrub()
        assert scrub is not None and scrub["deg"] == -30.0
        off = rt.table(t=MSG_YESTERLIGHT, active=0)
        hz.on_yesterlight(off, 0)
        assert hz.scrub() is None

    def test_echo_sets_highlight_and_reset_clears(self, horizon):
        rt, hz = horizon
        msg = rt.table(t=MSG_YESTERLIGHT, active=1, notch_dd=-300,
                       echo_dd=-450)
        hz.on_yesterlight(msg, 0)
        assert hz.scrub() is not None
        hz.reset()
        assert hz.scrub() is None

    def test_draw_with_scrub_does_not_error(self, horizon):
        rt, hz = horizon
        hz.on_yesterlight(rt.table(t=MSG_YESTERLIGHT, active=1,
                                   notch_dd=200), 0)
        opts = rt.table(now_ms=1000)
        hz.draw(opts)        # headless: HAS_FRAME false, pure state pass
