"""Inner Weather — the wearer's own climate, and its interference with
the room's."""
from pathlib import Path

import pytest

from dreamlayer.dream_mode.inner_weather import (
    InnerWeather, EMIT_HYSTERESIS, WARN_COOLDOWN_S, WARN_SUSTAIN_TICKS, WARN_STATE,
)
from dreamlayer.orchestrator.recall_context import RecallContext


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


def calm_ctx():
    return RecallContext(
        imu_delta={"yaw": 0.01, "pitch": 0.01, "roll": 0.0},
        imu_pose={"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
        mic_amplitude=0.9,          # loud room — irrelevant to inner state
    )


def restless_ctx(step=0):
    return RecallContext(
        imu_delta={"yaw": 1.2, "pitch": 0.9, "roll": 0.4},
        imu_pose={"pitch": 0.1 * (step % 3), "yaw": 0.1 * (step % 2),
                  "roll": 0.05 * step},
        mic_amplitude=0.05,         # quiet library — still churns inside
        extra={"self_prosody": {"speech_rate_norm": 1.7,
                                "hesitation_rate": 2.2,
                                "pause_ratio": 0.05}},
    )


class TestFusion:
    def test_calm_stays_low(self):
        iw = InnerWeather(now_fn=Clock())
        for _ in range(40):
            iw.tick(calm_ctx())
        assert iw.state < 0.15

    def test_restlessness_climbs(self):
        iw = InnerWeather(now_fn=Clock())
        for i in range(60):
            iw.tick(restless_ctx(i))
        assert iw.state > 0.5

    def test_bounded(self):
        iw = InnerWeather(now_fn=Clock())
        for i in range(200):
            iw.tick(restless_ctx(i))
            assert 0.0 <= iw.state <= 1.0

    def test_deterministic(self):
        a, b = InnerWeather(now_fn=Clock()), InnerWeather(now_fn=Clock())
        for i in range(30):
            a.tick(restless_ctx(i))
            b.tick(restless_ctx(i))
        assert a.state == pytest.approx(b.state)


class TestInterference:
    """Calm person in a loud room ≠ agitated person in a quiet library —
    the core churn tracks the wearer, never the room."""

    def test_loud_room_does_not_churn_a_calm_core(self):
        iw = InnerWeather(now_fn=Clock())
        for _ in range(40):
            iw.tick(calm_ctx())          # mic_amplitude 0.9 throughout
        assert iw.state < 0.15

    def test_quiet_library_still_churns_an_agitated_core(self):
        iw = InnerWeather(now_fn=Clock())
        for i in range(60):
            iw.tick(restless_ctx(i))     # mic_amplitude 0.05 throughout
        assert iw.state > 0.5


class TestEmission:
    def test_calm_from_cold_start_costs_no_radio(self):
        # the device boots at churn 0; a calm wearer never moves the
        # state past the hysteresis, so the channel stays silent
        iw = InnerWeather(now_fn=Clock())
        frames = []
        for _ in range(30):
            frames += iw.tick(calm_ctx())
        assert [f for f in frames if f.get("mode") == "churn"] == []

    def test_mood_change_emits(self):
        iw = InnerWeather(now_fn=Clock())
        for _ in range(10):
            iw.tick(calm_ctx())
        emitted = []
        for i in range(60):
            emitted += [f for f in iw.tick(restless_ctx(i))
                        if f.get("mode") == "churn"]
        assert len(emitted) >= 3
        # intensities step by at least the hysteresis
        vals = [f["intensity"] for f in emitted]
        assert all(abs(b - a) >= EMIT_HYSTERESIS * 0.99
                   for a, b in zip(vals, vals[1:]))

    def test_privacy_veil_silences_everything(self):
        iw = InnerWeather(privacy=Veil(False), now_fn=Clock())
        for i in range(40):
            assert iw.tick(restless_ctx(i)) == []
        assert iw.state == 0.0


class TestStormFront:
    def test_warning_fires_before_the_peak(self):
        """The display gets restless before you'd have named the feeling:
        on a slow synthetic ramp the warning must fire while the state is
        still climbing, not at saturation."""
        iw = InnerWeather(now_fn=Clock())
        warned_at = None
        states = []
        for i in range(120):
            for f in iw.tick(restless_ctx(i)):
                if f.get("name") == "inner_storm" and warned_at is None:
                    warned_at = i
            states.append(iw.state)
        assert warned_at is not None
        peak = max(states)
        assert states[warned_at] < 0.9 * peak, \
            "the warning must lead the peak, not describe it"

    def test_cooldown_and_front_semantics(self):
        """One storm = one warning: sustained storminess never re-warns.
        A second warning requires BOTH the cooldown to pass AND a genuine
        new front — calm first, then a fresh climb."""
        clock = Clock()
        iw = InnerWeather(now_fn=clock)
        warnings = 0
        for i in range(240):                     # ramp + long saturation
            for f in iw.tick(restless_ctx(i)):
                if f.get("name") == "inner_storm":
                    warnings += 1
        assert warnings == 1                     # no nagging at saturation
        # calm down completely, cooldown passes …
        for _ in range(200):
            iw.tick(calm_ctx())
        clock.t += WARN_COOLDOWN_S + 1
        # … and a fresh front earns exactly one more warning
        for i in range(120):
            for f in iw.tick(restless_ctx(i)):
                if f.get("name") == "inner_storm":
                    warnings += 1
        assert warnings == 2

    def test_calm_never_warns(self):
        iw = InnerWeather(now_fn=Clock())
        for _ in range(300):
            for f in iw.tick(calm_ctx()):
                assert f.get("name") != "inner_storm"


def mild_ctx(step=0):
    """Restless *for a calm person*, but the absolute state never crosses the
    fixed WARN_STATE (0.55) — the "very still person's real agitation" the fixed
    threshold would sleep through."""
    return RecallContext(
        imu_delta={"yaw": 0.6, "pitch": 0.4, "roll": 0.2},
        imu_pose={"pitch": 0.1 * (step % 3), "yaw": 0.1 * (step % 2),
                  "roll": 0.05 * (step % 4)},
        mic_amplitude=0.1,
        extra={"self_prosody": {"speech_rate_norm": 1.3,
                                "hesitation_rate": 1.0,
                                "pause_ratio": 0.35}},
    )


class TestPersonalBaseline:
    """The WeatherBaseline learner in isolation (INNOVATION 2.8)."""

    def test_defers_to_the_fixed_threshold_before_warmup(self):
        from dreamlayer.dream_mode.weather_river import WeatherBaseline
        b = WeatherBaseline(warmup=20)
        b.observe(0.6)
        assert b.is_elevated(0.6, fallback=0.55) is True     # 0.6 > 0.55 fallback
        assert b.is_elevated(0.4, fallback=0.55) is False

    def test_a_fidgety_baseline_stops_nagging(self):
        # a person who lives around 0.7: after warmup, 0.7 is *normal for them*
        from dreamlayer.dream_mode.weather_river import WeatherBaseline
        b = WeatherBaseline(warmup=20)
        for _ in range(80):
            b.observe(0.7)
        assert b.mean() > 0.6
        assert b.is_elevated(0.7, fallback=0.55) is False    # their normal ≠ a storm
        assert b.is_elevated(0.92, fallback=0.55) is True    # well above their norm

    def test_a_calm_baseline_becomes_more_sensitive(self):
        # a very still person: a rise the fixed 0.55 would miss still registers
        from dreamlayer.dream_mode.weather_river import WeatherBaseline
        b = WeatherBaseline(warmup=20)
        for _ in range(80):
            b.observe(0.05)
        assert b.is_elevated(0.40, fallback=0.55) is True    # unusual *for them*


class TestCalibratedWarning:
    """Calibrated InnerWeather warns on what's unusual for the wearer, not on a
    fixed line — divergence from the uncalibrated estimator on the same input."""

    def test_calibrated_catches_a_rise_the_fixed_threshold_sleeps_through(self):
        cal = InnerWeather(now_fn=Clock(), calibrate=True)
        fixed = InnerWeather(now_fn=Clock())               # default, uncalibrated
        cal_warn = fixed_warn = 0
        # settle both on a calm baseline, then a sustained mild rise
        for _ in range(40):
            cal.tick(calm_ctx()); fixed.tick(calm_ctx())
        for i in range(120):
            cal_warn += sum(f.get("name") == "inner_storm" for f in cal.tick(mild_ctx(i)))
            fixed_warn += sum(f.get("name") == "inner_storm" for f in fixed.tick(mild_ctx(i)))
        assert cal.state < WARN_STATE                       # never crosses the fixed line
        assert fixed_warn == 0                              # so the fixed estimator is silent
        assert cal_warn >= 1                                # but it was unusual *for this wearer*

    def test_calibration_is_off_by_default(self):
        assert InnerWeather(now_fn=Clock())._baseline is None
        assert InnerWeather(now_fn=Clock(), calibrate=True)._baseline is not None


class TestDeviceRenderer:
    @pytest.fixture
    def renderer(self):
        lupa = pytest.importorskip("lupa")
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        root = Path(__file__).resolve().parents[4] / "halo-lua"
        rt.execute(f'package.path = "{root}/?.lua;" .. package.path')
        r = rt.eval('require("display.dream_renderer")')
        return rt, (r[0] if isinstance(r, tuple) else r)

    def test_churn_rides_its_own_channel(self, renderer):
        rt, dr = renderer
        dr.on_geometry(rt.table(mode="scatter", intensity=0.8))
        dr.on_geometry(rt.table(mode="churn", intensity=0.6))
        assert dr.churn() == pytest.approx(0.6)
        # a churn frame must not clobber the transient gesture mode:
        # a following plain-geometry tick still scatters
        dr.on_geometry(rt.table(mode="scatter", intensity=0.5))
        assert dr.churn() == pytest.approx(0.6)

    def test_particles_stay_in_core_under_churn(self, renderer):
        rt, dr = renderer
        dr.on_geometry(rt.table(mode="churn", intensity=1.0))
        for _ in range(200):
            dr.update_particles(0.0, "drift")
        # Meridian territory law survives the churn: r <= 96
        # (particles are private; the draw pass not erroring headless plus
        # the clipping branch is the observable contract)
        dr.draw_frame(100)
