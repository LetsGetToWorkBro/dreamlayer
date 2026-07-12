"""WCAG 2.3.1 flash-safety analyzer: verify the eye-safety claim over the real
rendered output, not just the static Hz cap. Needs numpy + Pillow."""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")

from dreamlayer.reality_compiler.v2 import native
from dreamlayer.reality_compiler.v2.figment import (
    Figment, Scene, TextLine, PulseSpec, Transition, END,
)
from dreamlayer.reality_compiler.v2.flash_safety import (
    analyze_figment, count_flashes, relative_luminance, FlashReport,
    FLASH_LIMIT, DEFAULT_AREA_MIN,
)


class TestLuminance:
    def test_black_and_white(self):
        assert relative_luminance((0, 0, 0)) == 0.0
        assert relative_luminance((255, 255, 255)) == pytest.approx(1.0)

    def test_monotonic(self):
        assert relative_luminance((60, 60, 60)) < relative_luminance((200, 200, 200))


class TestCountFlashes:
    def _square(self, hz, secs=3.0, sr=40, lum=0.9, area=1.0):
        # a full-amplitude square wave at `hz`, sampled at `sr` Hz
        s = []
        n = int(secs * sr)
        for i in range(n):
            t = i / sr
            on = (int(t * hz * 2) % 2) == 0
            s.append((t, lum if on else 0.0, area))
        return s

    def test_four_hz_large_area_is_unsafe(self):
        assert count_flashes(self._square(4)) > FLASH_LIMIT

    def test_two_hz_is_within_limit(self):
        assert count_flashes(self._square(2)) <= FLASH_LIMIT

    def test_small_area_is_exempt(self):
        # the same 4 Hz flash, but covering only 5% of the glass → exempt
        assert count_flashes(self._square(4, area=0.05)) == 0.0

    def test_small_luminance_change_does_not_count(self):
        assert count_flashes(self._square(4, lum=0.05)) == 0.0


class TestFigmentAnalysis:
    def test_native_figments_are_flash_safe(self):
        for fig in (native.timer_figment(30),
                    native.interval_figment(30, 15, rounds=3)):
            rep = analyze_figment(fig)
            assert isinstance(rep, FlashReport) and rep.ok, str(rep)

    def test_pulseless_figment_is_trivially_safe(self):
        fig = native.clock_figment()
        rep = analyze_figment(fig)
        assert rep.ok and rep.general_hz == 0 and rep.red_hz == 0

    def _strobe(self, rate, color):
        fig = Figment(name="strobe", initial="a")
        fig.add_scene(Scene(id="a", duration_sec=5.0, tick="countdown",
                            lines=[TextLine("HI", row=1)],
                            pulse=PulseSpec(window_sec=4.0, rate_hz=rate, color=color),
                            on_timeout=[Transition(target=END)]))
        return fig

    def test_ring_pulse_is_exempt_by_area_at_the_default_threshold(self):
        # even a max-rate red ring flash is safe by the small-area exemption:
        # the pulse ring covers far less than the near-eye area threshold
        rep = analyze_figment(self._strobe(4.0, "accent_error"))
        assert rep.ok

    def test_same_flash_is_flagged_when_area_qualifies(self):
        # drop the area exemption → the 4/s red ring flash now exceeds the limit,
        # proving the WCAG counting actually fires (not a silent pass)
        rep = analyze_figment(self._strobe(4.0, "accent_error"), area_min=0.0)
        assert not rep.ok and rep.red_hz > FLASH_LIMIT
        assert any(kind == "red" for _, kind, _ in rep.offenders)

    def test_slow_pulse_stays_safe_even_without_the_area_exemption(self):
        rep = analyze_figment(self._strobe(2.0, "accent_error"), area_min=0.0)
        assert rep.ok and rep.red_hz <= FLASH_LIMIT


class TestGate:
    """The flash golden: every built-in figment must pass at the default bar."""
    def test_all_native_figments_pass(self):
        figs = [native.timer_figment(10), native.timer_figment(180),
                native.interval_figment(20, 10, rounds=8),
                native.interval_figment(45, 15),
                native.clock_figment(), native.rosetta_figment(),
                native.morning_brief_figment()]
        bad = [str(analyze_figment(f)) for f in figs if not analyze_figment(f).ok]
        assert not bad, bad
