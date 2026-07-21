"""dream_mode/dream_style.py — see the world as a painting (#12).

The neural tier (onnxruntime + a user .onnx) isn't in CI, so these pin two
things: the ALWAYS-ON painterly wash genuinely repaints a frame (and never
raises), and the neural stylizer degrades to None so default_stylizer() always
hands back a working brush.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.dream_mode.dream_style import (
    DreamStylizer, PainterlyFilter, default_stylizer,
)


def _frame():
    rng = np.arange(16 * 16 * 3, dtype=np.uint8).reshape(16, 16, 3)
    return rng


class TestPainterly:
    def test_repaints_and_preserves_shape(self):
        f = _frame()
        out = PainterlyFilter().stylize(f)
        assert out is not None
        assert out.shape == f.shape and out.dtype == np.uint8
        # it must actually change the image, not pass it through
        assert not np.array_equal(out, f)

    def test_quantises_to_few_tones(self):
        # a smooth ramp should collapse to at most `levels` distinct values/channel
        ramp = np.tile(np.linspace(0, 255, 32, dtype=np.uint8)[:, None, None], (1, 4, 3))
        out = PainterlyFilter(levels=5).stylize(ramp)
        assert out is not None
        # posterised → far fewer unique levels than the 32-step ramp had
        assert len(np.unique(out[:, :, 0])) <= 12

    def test_bad_frame_returns_none_never_raises(self):
        assert PainterlyFilter().stylize(object()) is None
        assert PainterlyFilter().stylize(np.zeros((0, 0, 3), np.uint8)) is None

    def test_grayscale_is_accepted(self):
        out = PainterlyFilter().stylize(np.full((8, 8), 120, np.uint8))
        assert out is not None and out.shape == (8, 8, 3)

    def test_single_channel_hw1_is_painted(self):
        # (H,W,1) grayscale/depth layout must paint, not silently return None
        out = PainterlyFilter().stylize(np.full((8, 8, 1), 120, np.uint8))
        assert out is not None and out.shape == (8, 8, 3)


class TestNeuralFallback:
    def test_unavailable_without_runtime_or_model(self):
        s = DreamStylizer()                      # no model path
        assert s.ready is False
        assert s.stylize(_frame()) is None

    def test_missing_model_file_is_not_ready(self, tmp_path):
        s = DreamStylizer(str(tmp_path / "nope.onnx"))
        assert s.ready is False
        assert s.stylize(_frame()) is None


def test_default_stylizer_always_returns_a_brush(tmp_path):
    s = default_stylizer(str(tmp_path / "absent.onnx"))
    assert s is not None
    out = s.stylize(_frame())               # painterly fallback → a real image
    assert out is not None and out.dtype == np.uint8


def test_dream_style_capability_registered():
    from dreamlayer import capabilities as C
    cap = {c.key: c for c in C.CAPABILITIES}.get("dream_style")
    assert cap is not None, "dream_style capability missing"
    assert cap.extra == "dream-style"
    assert "onnxruntime" in cap.modules
    assert cap.seam == "dream_mode/dream_style.py"
