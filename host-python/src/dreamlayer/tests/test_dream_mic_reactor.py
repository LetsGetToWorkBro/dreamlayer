"""Tests for MicReactor FFT → palette shift mapping."""
import pytest
from dreamlayer.dream_mode.mic_reactor import MicReactor
from dreamlayer.orchestrator.recall_context import RecallContext


def make_ctx(fft=None, amplitude=0.0):
    ctx = RecallContext()
    ctx.mic_fft = fft or [0.0] * 32
    ctx.mic_amplitude = amplitude
    return ctx


def test_no_output_without_mic_data():
    r = MicReactor()
    ctx = RecallContext()   # no mic data
    assert r.tick(ctx) is None


def test_returns_palette_command():
    r = MicReactor()
    ctx = make_ctx([0.5] * 32, 0.5)
    cmd = r.tick(ctx)
    assert cmd is not None
    assert cmd["t"] == "palette"
    assert "colors" in cmd
    assert isinstance(cmd["colors"], list)
    assert len(cmd["colors"]) == 4   # _AMBIENT_SLOTS has 4 entries


def test_palette_color_fields():
    r = MicReactor()
    ctx = make_ctx([0.5] * 32, 0.5)
    cmd = r.tick(ctx)
    for color in cmd["colors"]:
        assert "idx" in color
        assert "y"   in color
        assert "cb"  in color
        assert "cr"  in color


def test_ycbcr_values_in_range():
    r = MicReactor()
    ctx = make_ctx([1.0] * 32, 1.0)   # max energy
    cmd = r.tick(ctx)
    for c in cmd["colors"]:
        assert 80  <= c["y"]  <= 900
        assert 300 <= c["cb"] <= 800
        assert 300 <= c["cr"] <= 800


def test_silence_produces_cool_baseline():
    r = MicReactor(smoothing=1.0)   # no smoothing for test
    ctx = make_ctx([0.0] * 32, 0.0)
    cmd = r.tick(ctx)
    # With silence, Y should be near _BASE_Y (420), Cb near _BASE_CB (560)
    for c in cmd["colors"]:
        assert abs(c["y"]  - 420) < 50
        assert abs(c["cb"] - 560) < 50


def test_duration_ms_present():
    r = MicReactor()
    ctx = make_ctx([0.3] * 32, 0.3)
    cmd = r.tick(ctx)
    assert cmd["duration_ms"] == 2000
