"""Timbre — see who's speaking before you turn around."""
from pathlib import Path

import pytest

from dreamlayer.dream_mode.timbre_reactor import (
    TimbreReactor, MSG_TIMBRE, HOLD_S,
)
from dreamlayer.orchestrator.recall_context import RecallContext
from dreamlayer.social_lens.timbre import (
    timbre_signature, signature_distance, POINTS,
)

MAYA = {"pitch_mean_hz": 210.0, "pitch_variance": 120.0, "jitter_pct": 0.8,
        "shimmer_pct": 1.4, "hesitation_rate": 0.3, "pause_ratio": 0.22,
        "speech_rate_norm": 1.1, "energy_db": -18.0}
DRE = {"pitch_mean_hz": 105.0, "pitch_variance": 340.0, "jitter_pct": 2.6,
       "shimmer_pct": 4.8, "hesitation_rate": 1.2, "pause_ratio": 0.4,
       "speech_rate_norm": 0.8, "energy_db": -9.0}


class TestSignature:
    def test_stable_across_sessions(self):
        assert timbre_signature(MAYA) == timbre_signature(dict(MAYA))

    def test_twelve_points_in_range(self):
        pts = timbre_signature(MAYA)
        assert len(pts) == POINTS
        assert all(1 <= p <= 15 for p in pts)

    def test_different_voices_draw_differently(self):
        assert signature_distance(timbre_signature(MAYA),
                                  timbre_signature(DRE)) >= 8

    def test_small_baseline_drift_small_shape_drift(self):
        drifted = dict(MAYA, pitch_mean_hz=214.0)
        assert signature_distance(timbre_signature(MAYA),
                                  timbre_signature(drifted)) <= 6

    def test_empty_baseline_still_shapes(self):
        pts = timbre_signature({})
        assert len(pts) == POINTS and all(1 <= p <= 15 for p in pts)


class Baselines:
    """Stub NarrativeStore: contact id → object with prosody_mean."""

    def __init__(self, table):
        self._t = table

    def get_baseline(self, cid):
        row = self._t.get(cid)
        if row is None:
            return None
        return type("B", (), {"prosody_mean": row})()


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class Veil:
    def __init__(self, allow=True):
        self.allow = allow

    def allow_capture(self):
        return self.allow


def ctx(speaker=None, direction=None):
    extra = {}
    if direction is not None:
        extra["voice_direction_deg"] = direction
    return RecallContext(speaker=speaker, extra=extra)


class TestReactor:
    def make(self, allow=True):
        clock = Clock()
        reactor = TimbreReactor(
            baselines=Baselines({"maya": MAYA, "dre": DRE}),
            privacy=Veil(allow), now_fn=clock)
        return reactor, clock

    def test_silence_emits_nothing(self):
        reactor, _ = self.make()
        assert reactor.tick(ctx(speaker=None)) is None

    def test_known_voice_draws_its_timbre(self):
        reactor, _ = self.make()
        frame = reactor.tick(ctx(speaker="maya", direction=45.0))
        assert frame["t"] == MSG_TIMBRE
        assert frame["known"] == 1
        assert frame["side_dd"] == 450
        assert frame["points"] == timbre_signature(MAYA)

    def test_same_person_same_shape_every_time(self):
        reactor, clock = self.make()
        f1 = reactor.tick(ctx(speaker="maya"))
        clock.t += HOLD_S + 1
        f2 = reactor.tick(ctx(speaker="maya"))
        assert f1["points"] == f2["points"]

    def test_stranger_renders_as_static_never_identity(self):
        reactor, clock = self.make()
        f1 = reactor.tick(ctx(speaker="stranger"))
        assert f1["known"] == 0
        clock.t += HOLD_S + 1
        f2 = reactor.tick(ctx(speaker="stranger"))
        # static is noise: it does not repeat like an identity would
        assert f1["points"] != f2["points"]
        # and it never resembles a real contact's signature
        assert f1["points"] != timbre_signature(MAYA)

    def test_unknown_contact_id_is_static_too(self):
        reactor, _ = self.make()
        assert reactor.tick(ctx(speaker="nobody"))["known"] == 0

    def test_rate_limited_per_speaker(self):
        reactor, clock = self.make()
        assert reactor.tick(ctx(speaker="maya")) is not None
        assert reactor.tick(ctx(speaker="maya")) is None
        # a different speaker is not blocked by maya's hold
        assert reactor.tick(ctx(speaker="dre")) is not None
        clock.t += HOLD_S + 0.1
        assert reactor.tick(ctx(speaker="maya")) is not None

    def test_default_direction_straight_ahead(self):
        reactor, _ = self.make()
        assert reactor.tick(ctx(speaker="maya"))["side_dd"] == -900

    def test_privacy_veil_silences_the_rim(self):
        reactor, _ = self.make(allow=False)
        assert reactor.tick(ctx(speaker="maya")) is None


class TestDeviceRenderer:
    @pytest.fixture
    def renderer(self):
        lupa = pytest.importorskip("lupa")
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        root = Path(__file__).resolve().parents[4] / "halo-lua"
        rt.execute(f'package.path = "{root}/?.lua;" .. package.path')
        r = rt.eval('require("display.dream_renderer")')
        return rt, (r[0] if isinstance(r, tuple) else r)

    def test_lockstep_constant(self):
        root = Path(__file__).resolve().parents[4] / "halo-lua"
        lua = (root / "ble" / "message_types.lua").read_text()
        assert f'"{MSG_TIMBRE}"' in lua

    def test_on_timbre_stores_and_expires(self, renderer):
        rt, dr = renderer
        msg = rt.table(t=MSG_TIMBRE, known=1, side_dd=-900,
                       points=rt.table(*[8] * 12))
        dr.on_timbre(msg, 0)
        live = dr.timbre(100)
        assert live is not None and live["known"] is True
        assert dr.timbre(99999) is None      # TTL expired

    def test_draw_frame_headless_safe(self, renderer):
        rt, dr = renderer
        dr.on_timbre(rt.table(t=MSG_TIMBRE, known=0, side_dd=200,
                              points=rt.table(*range(1, 13))), 0)
        dr.draw_frame(50)                    # must not error headless
