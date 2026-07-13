"""Boundary/precision unit tests for the flash-safety helpers (flash_safety.py).

test_flash_safety.py exercises analyze_figment end to end, but that leaves the
internal helpers — the sRGB linearization, the WCAG channel weights, the red
ratio, and the 1-second window counter — pinned only loosely. Mutation testing
showed it: 88 of 230 mutants in flash_safety.py survived, because nothing nailed
the exact constants and the counting boundaries.

These tests close that. They pin the eye-safety math to the WCAG numbers it
claims to implement: the luminance coefficients (0.2126/0.7152/0.0722), the
linearization (÷255, ÷12.92, the 0.03928 knee, the 2.4 exponent), the flash
qualifiers (≥10% luminance delta, darker state <0.80, strict 1-second window),
and the red-flash ratio. A flipped operator or a nudged constant in the
analyzer now fails a test. Needs numpy; skipped headlessly when absent.

Result: the mutation score rose from 62% to 88% (203/230). The residual 27 are
not test holes but unreachable-or-equivalent mutants: (a) the *general-flash*
accounting path in analyze_figment never fires because a figment's only flasher
is the ~6%-area pulse ring, which cannot move mean luminance the ≥10% a general
flash needs — only the red path triggers (count_flashes stays fully covered here
for the future full-frame sampler the module anticipates); (b) the numpy-absent
and renderer-returned-None degradation branches can't be hit with the deps
present; (c) a couple are equivalent (l1>=l0 where equality is already excluded
by the delta gate; a/256 vs a/255 inside a branch predicate that never flips for
byte inputs). The enforced zero-survivor gate stays on contracts.py; this is a
coverage-hardening pass, verified by mutation testing, not a new blocking gate."""
import pytest

np = pytest.importorskip("numpy")

from dreamlayer.reality_compiler.v2.flash_safety import (   # noqa: E402
    _linear, relative_luminance, red_ratio, count_flashes, _measure,
    _pulse_frames, LUM_DELTA, DARK_MAX,
)


class TestLinear:
    def test_endpoints(self):
        assert _linear(0) == 0.0
        assert _linear(255) == pytest.approx(1.0)

    def test_knee_is_inclusive(self):
        # at exactly c/255 == 0.03928 the linear branch applies (<=, not <)
        knee = 0.03928 * 255.0
        assert _linear(knee) == pytest.approx(knee / 255.0 / 12.92, rel=1e-9)

    def test_linear_branch_value(self):
        # c=10 → 10/255 = 0.03922 ≤ 0.03928, so the ÷12.92 linear branch.
        # Pins the ÷255 and ÷12.92 (kills *12.92, ÷13.92).
        assert _linear(10) == pytest.approx(10 / 255.0 / 12.92, rel=1e-6)

    def test_power_branch_value(self):
        # c=128 sits in the gamma branch: pins 0.055, 1.055, and the 2.4 exponent
        expect = ((128 / 255.0 + 0.055) / 1.055) ** 2.4
        assert _linear(128) == pytest.approx(expect, rel=1e-6)


class TestRelativeLuminance:
    def test_channel_weights(self):
        # pure primaries isolate each WCAG coefficient — kills channel swaps and
        # weight-constant mutations
        assert relative_luminance((255, 0, 0)) == pytest.approx(0.2126, rel=1e-4)
        assert relative_luminance((0, 255, 0)) == pytest.approx(0.7152, rel=1e-4)
        assert relative_luminance((0, 0, 255)) == pytest.approx(0.0722, rel=1e-4)

    def test_black_and_white(self):
        assert relative_luminance((0, 0, 0)) == 0.0
        assert relative_luminance((255, 255, 255)) == pytest.approx(1.0)


class TestRedRatio:
    def test_pure_red_is_one(self):
        assert red_ratio((255, 0, 0)) == 1.0

    def test_gray_is_a_third(self):
        assert red_ratio((100, 100, 100)) == pytest.approx(1 / 3)

    def test_zero_total_is_zero(self):
        assert red_ratio((0, 0, 0)) == 0.0        # the total==0 guard branch

    def test_asymmetric_triple_pins_the_sum(self):
        # distinct channels → the sum and the numerator are all pinned; kills the
        # +/- and index-swap mutations on total
        assert red_ratio((200, 50, 10)) == pytest.approx(200 / 260, rel=1e-6)


class TestCountFlashes:
    A = 1.0     # area passes the exemption in all these

    def test_counts_only_rising_edges(self):
        # up, down, up → two rising transitions, the fall is not a flash
        s = [(0.0, 0.0, self.A), (0.1, 0.9, self.A),
             (0.2, 0.0, self.A), (0.3, 0.9, self.A)]
        assert count_flashes(s) == 2.0

    def test_delta_is_inclusive_at_ten_percent(self):
        # exactly LUM_DELTA qualifies (≥, not >)
        s = [(0.0, 0.0, self.A), (0.1, LUM_DELTA, self.A)]
        assert count_flashes(s) == 1.0

    def test_delta_is_a_difference_not_a_sum(self):
        # a small rising step between two nonzero levels: |Δ|=0.05 < LUM_DELTA so
        # it must NOT count; a mutant using l1+l0 (=1.05) would wrongly count it
        s = [(0.0, 0.5, self.A), (0.1, 0.55, self.A)]
        assert count_flashes(s) == 0.0

    def test_area_threshold_is_inclusive(self):
        # area exactly at the threshold qualifies (≥, not >)
        s = [(0.0, 0.0, 0.20), (0.1, 0.9, 0.20)]
        assert count_flashes(s, area_min=0.20) == 1.0

    def test_darker_state_is_strict_below_080(self):
        # min(l0,l1) == DARK_MAX must NOT count (strict <, not <=)
        s = [(0.0, DARK_MAX, self.A), (0.1, DARK_MAX + 0.15, self.A)]
        assert count_flashes(s) == 0.0

    def test_window_is_half_open(self):
        # a rising edge exactly one second later is OUTSIDE [t, t+1): strict <
        s = [(0.0, 0.0, self.A), (0.1, 0.9, self.A),
             (0.2, 0.0, self.A),                       # settle low...
             (1.1, 0.9, self.A)]                       # ...rise again at +1.0s
        assert count_flashes(s) == 1.0

    def test_first_sample_is_not_wrapped(self):
        # range starts at 1: the first sample has no predecessor, so a bright
        # start next to a dark end must not synthesize an edge at t=0
        s = [(0.0, 0.9, self.A), (0.1, 0.0, self.A),
             (0.2, 0.9, self.A), (0.3, 0.0, self.A)]
        assert count_flashes(s) == 1.0

    def test_small_area_is_exempt(self):
        s = [(0.0, 0.0, 0.01), (0.1, 0.9, 0.01)]      # 1% area → below threshold
        assert count_flashes(s) == 0.0


class TestMeasure:
    def _img(self, rgb, h=2, w=2):
        return np.tile(np.array(rgb, dtype=np.uint8), (h, w, 1))

    def test_dtype_is_float32(self):
        rgb, _lum = _measure(self._img((10, 20, 30)))
        assert rgb.dtype == np.float32

    def test_white_and_black_luminance(self):
        _r, lum_w = _measure(self._img((255, 255, 255)))
        _r, lum_b = _measure(self._img((0, 0, 0)))
        assert float(lum_w.mean()) == pytest.approx(1.0)
        assert float(lum_b.mean()) == 0.0

    def test_gray_pins_the_255_divisor(self):
        # 128/255 (not /256): a dark-ish gray value pins the divisor and the knee
        _r, lum = _measure(self._img((128, 128, 128)))
        expect = ((128 / 255.0 + 0.055) / 1.055) ** 2.4
        assert float(lum.mean()) == pytest.approx(expect, rel=1e-5)

    def test_dark_gray_pins_the_linear_knee(self):
        # value 5 sits in the ÷12.92 linear branch — kills a mutated where()
        # predicate that pushes it into the gamma branch
        _r, lum = _measure(self._img((5, 5, 5)))
        assert float(lum.mean()) == pytest.approx(5 / 255.0 / 12.92, rel=1e-5)

    def test_channel_weights_and_indices(self):
        # distinct primaries pin which channel each WCAG weight multiplies —
        # kills index swaps in the luminance dot product
        _r, lum_red = _measure(self._img((255, 0, 0)))
        _r, lum_grn = _measure(self._img((0, 255, 0)))
        _r, lum_blu = _measure(self._img((0, 0, 255)))
        assert float(lum_red.mean()) == pytest.approx(0.2126, rel=1e-4)
        assert float(lum_grn.mean()) == pytest.approx(0.7152, rel=1e-4)
        assert float(lum_blu.mean()) == pytest.approx(0.0722, rel=1e-4)

    def test_knee_predicate_is_inclusive(self):
        # a float pixel exactly at the 0.03928 knee takes the linear branch (≤);
        # (a float array so the value lands on the knee, not rounded to a byte)
        knee = np.float32(0.03928 * 255.0)
        img = np.full((1, 1, 3), knee, dtype=np.float32)
        _r, lum = _measure(img)
        assert float(lum.mean()) == pytest.approx(0.03928 / 12.92, rel=1e-5)


class TestPulseFrames:
    def _scene(self):
        from dreamlayer.reality_compiler.v2.figment import (
            Figment, Scene, TextLine, PulseSpec, Transition, END,
        )
        fig = Figment(name="p", initial="a")
        fig.add_scene(Scene(
            id="a", duration_sec=5.0, tick="countdown",
            lines=[TextLine("HI", row=1, size="lg", color="accent_error")],
            pulse=PulseSpec(window_sec=4.0, rate_hz=2.0, color="accent_error"),
            on_timeout=[Transition(target=END)]))
        return fig.scenes["a"]

    def test_on_frame_pulses_off_frame_does_not(self):
        on, off = _pulse_frames("a", self._scene())
        assert on.pulse_on is True and off.pulse_on is False
        assert on.pulse_color == "accent_error"
        assert off.pulse_color is None

    def test_scene_id_and_line_attrs_carried(self):
        on, off = _pulse_frames("a", self._scene())
        assert on.scene == "a" and off.scene == "a"
        assert len(off.lines) == 1                # off frame keeps the same lines
        line = on.lines[0]                # a ResolvedLine: TextLine.content → .text
        assert line.text == "HI" and line.row == 1
        assert line.size == "lg" and line.color == "accent_error"


class TestFigmentTrips:
    """analyze_figment against real rendered frames, at the reporting boundaries
    the end-to-end tests leave loose: the red-flash accounting, the ok cutoff,
    and that a non-pulsing scene is skipped (continue) not aborted (break).
    Needs the renderer; skipped when Pillow is absent."""

    def _red_strobe(self, rate):
        from dreamlayer.reality_compiler.v2.figment import (
            Figment, Scene, TextLine, PulseSpec, Transition, END,
        )
        fig = Figment(name="strobe", initial="a")
        fig.add_scene(Scene(
            id="a", duration_sec=5.0, tick="countdown",
            lines=[TextLine("HI", row=1)],
            pulse=PulseSpec(window_sec=4.0, rate_hz=rate, color="accent_error"),
            on_timeout=[Transition(target=END)]))
        return fig

    def setup_method(self):
        pytest.importorskip("PIL")
        from dreamlayer.reality_compiler.v2.flash_safety import analyze_figment
        # skip cleanly if the renderer can't produce frames in this env
        rep = analyze_figment(self._red_strobe(4.0), area_min=0.0)
        if not rep.offenders:
            pytest.skip("renderer produced no measurable frames")

    def test_red_flash_is_accounted(self):
        from dreamlayer.reality_compiler.v2.flash_safety import (
            analyze_figment, FLASH_LIMIT,
        )
        rep = analyze_figment(self._red_strobe(4.0), area_min=0.0)
        assert rep.red_hz == 4.0 and rep.red_hz > FLASH_LIMIT
        assert not rep.ok
        assert ("a", "red", 4.0) in rep.offenders     # exact offender tuple

    def test_ok_boundary_is_inclusive_at_the_limit(self):
        # worst == FLASH_LIMIT is still ok (<=, not <): a 3/s red strobe passes
        from dreamlayer.reality_compiler.v2.flash_safety import analyze_figment
        rep = analyze_figment(self._red_strobe(3.0), area_min=0.0)
        assert rep.red_hz == 3.0 and rep.ok

    def test_nonpulsing_scene_is_skipped_not_aborted(self):
        # a plain scene ahead of the pulsing one must be `continue`d past, not
        # `break`ed on — else the real flasher downstream goes unmeasured
        from dreamlayer.reality_compiler.v2.figment import (
            Figment, Scene, TextLine, PulseSpec, Transition, END,
        )
        from dreamlayer.reality_compiler.v2.flash_safety import analyze_figment
        fig = Figment(name="two", initial="plain")
        fig.add_scene(Scene(id="plain", duration_sec=2.0,
                            lines=[TextLine("hi", row=1)],
                            on_timeout=[Transition(target="ring")]))
        fig.add_scene(Scene(
            id="ring", duration_sec=5.0, tick="countdown",
            lines=[TextLine("HI", row=1)],
            pulse=PulseSpec(window_sec=4.0, rate_hz=4.0, color="accent_error"),
            on_timeout=[Transition(target=END)]))
        rep = analyze_figment(fig, area_min=0.0)
        assert any(sid == "ring" for sid, _k, _hz in rep.offenders)
