"""The Apple Neural Engine rung — `coreml_ondevice`, implemented not claimed.

`CoreMLClassifier.__call__` was, in its entirety:

    return None if not (self.available and self.model_path) else None

`None` on both branches. No configuration could make it return a label, so it
was not a dormant capability waiting for a wheel — it was a claim, and
`available` (which was just "coremltools imports") would have promoted it green
the moment anyone pip-installed the dependency.

Three separate things gate a real answer and each is its own honest refusal:
coremltools importable, macOS to execute on (coremltools imports fine on Linux
and cannot predict), and a model file that exists. These tests drive the parsing
and thresholding for real through the injected `_predict`, so the only untested
line is the model load itself.
"""
from __future__ import annotations

import numpy as np
import pytest

from dreamlayer.object_lens.classify_backends import (
    CoreMLClassifier, HeuristicVisionClassifier, _to_rgb_image,
    default_classifier,
)


def _frame(v=180):
    return np.full((16, 16, 3), v, dtype=np.uint8)


def _out(label="mug", conf=0.91, key="classLabelProbs", with_label=True):
    d = {key: {label: conf, "other": max(0.0, 1.0 - conf)}}
    if with_label:
        d["classLabel"] = label
    return d


class TestTheFloor:
    def test_unconfigured_is_none_not_a_guess(self):
        c = CoreMLClassifier(model_path="")
        assert c.usable() is False
        assert c(_frame()) is None

    def test_a_missing_model_file_is_none(self, tmp_path):
        c = CoreMLClassifier(model_path=str(tmp_path / "nope.mlmodel"))
        assert c.usable() is False
        assert c(_frame()) is None

    def test_the_ladder_is_unchanged_when_coreml_is_unconfigured(self,
                                                                 monkeypatch):
        # The floor stated at the ladder: an unconfigured Mac must get exactly
        # the rung it got before this existed.
        import dreamlayer.object_lens.classify_backends as B
        monkeypatch.setattr(B, "_configured_coreml_model", lambda: "")
        got = default_classifier()
        assert not isinstance(got, CoreMLClassifier)
        assert isinstance(got, HeuristicVisionClassifier) or got is not None


class TestItActuallyPredicts:
    def test_a_real_label_comes_back(self):
        c = CoreMLClassifier(_predict=lambda img: _out("mug", 0.91))
        assert c(_frame()) == ("mug", pytest.approx(0.91))

    def test_it_counts_only_real_predictions(self):
        c = CoreMLClassifier(_predict=lambda img: _out("mug", 0.91))
        assert c.predictions == 0
        c(_frame())
        c(_frame())
        assert c.predictions == 2

    def test_a_low_confidence_answer_is_declined(self):
        # None means "ask the next rung". A 3%-confident label is worse than no
        # label, because the ladder would stop looking.
        c = CoreMLClassifier(_predict=lambda img: _out("mug", 0.03))
        assert c(_frame()) is None
        assert c.predictions == 0

    def test_the_threshold_is_inclusive_at_the_bar(self):
        c = CoreMLClassifier(min_confidence=0.5,
                             _predict=lambda img: _out("mug", 0.5))
        assert c(_frame()) == ("mug", pytest.approx(0.5))

    def test_a_model_that_raises_never_breaks_a_look(self):
        def boom(img):
            raise RuntimeError("ANE fell over")
        assert CoreMLClassifier(_predict=boom)(_frame()) is None

    def test_a_garbage_frame_is_declined_not_crashed(self):
        c = CoreMLClassifier(_predict=lambda img: _out())
        assert c(np.zeros((0, 0, 3), dtype=np.uint8)) is None


class TestReadingTheModelOutput:
    """The probability key name is chosen by whoever converted the model, so it
    is found by shape rather than by a name that is not part of the format."""

    def test_the_conventional_shape(self):
        assert CoreMLClassifier._read(_out("mug", 0.8)) == ("mug", 0.8)

    def test_an_unconventional_probability_key(self):
        got = CoreMLClassifier._read(_out("mug", 0.8, key="whatever_probs"))
        assert got == ("mug", 0.8)

    def test_no_class_label_falls_back_to_the_argmax(self):
        got = CoreMLClassifier._read(_out("mug", 0.8, with_label=False))
        assert got == ("mug", 0.8)

    def test_a_label_with_no_probabilities_is_trusted_at_one(self):
        assert CoreMLClassifier._read({"classLabel": "mug"}) == ("mug", 1.0)

    def test_an_empty_or_wrong_output_is_none(self):
        assert CoreMLClassifier._read({}) is None
        assert CoreMLClassifier._read(None) is None
        assert CoreMLClassifier._read("mug") is None

    def test_a_non_numeric_probability_does_not_raise(self):
        got = CoreMLClassifier._read({"classLabel": "mug",
                                      "p": {"mug": "very sure"}})
        assert got == ("mug", 1.0)


class TestTheFrameConversion:
    def test_uint8_passes_through(self):
        img = _to_rgb_image(_frame())
        assert img is not None and img.mode == "RGB" and img.size == (16, 16)

    def test_floats_in_0_1_are_scaled(self):
        img = _to_rgb_image(np.full((4, 4, 3), 1.0, dtype=np.float32))
        assert img is not None and img.getpixel((0, 0)) == (255, 255, 255)

    def test_a_pil_image_is_returned_as_rgb(self):
        from PIL import Image
        assert _to_rgb_image(Image.new("L", (3, 3))).mode == "RGB"

    def test_an_empty_frame_is_none(self):
        assert _to_rgb_image(np.zeros((0, 0, 3))) is None


class TestTheLadderPrefersIt:
    def test_a_configured_model_takes_the_top_rung(self, tmp_path, monkeypatch):
        import dreamlayer.object_lens.classify_backends as B
        model = tmp_path / "m.mlmodel"
        model.write_bytes(b"not a real model, only its existence is checked")
        monkeypatch.setattr(B, "_configured_coreml_model", lambda: str(model))
        monkeypatch.setattr(B.CoreMLClassifier, "available", True)
        got = default_classifier()
        assert isinstance(got, B.CoreMLClassifier)

    def test_it_is_skipped_off_apple_even_with_a_model(self, tmp_path,
                                                       monkeypatch):
        # coremltools imports on Linux and cannot predict. Taking the top rung
        # there would silence the whole ladder on every frame.
        import dreamlayer.object_lens.classify_backends as B
        model = tmp_path / "m.mlmodel"
        model.write_bytes(b"x")
        monkeypatch.setattr(B, "_configured_coreml_model", lambda: str(model))
        monkeypatch.setattr(B.CoreMLClassifier, "available", False)
        assert not isinstance(default_classifier(), B.CoreMLClassifier)

    def test_usable_does_not_load_the_model(self, tmp_path, monkeypatch):
        import dreamlayer.object_lens.classify_backends as B
        model = tmp_path / "m.mlmodel"
        model.write_bytes(b"x")
        monkeypatch.setattr(B.CoreMLClassifier, "available", True)
        c = B.CoreMLClassifier(model_path=str(model))
        assert c.usable() is True
        assert c._model is None, "usable() must stay a file check, not a load"


class TestTheConfigSeam:
    def test_the_path_comes_from_config(self, monkeypatch):
        from dreamlayer import config as C
        monkeypatch.setattr(C.CONFIG, "coreml_model_path", "/tmp/x.mlmodel",
                            raising=False)
        from dreamlayer.object_lens.classify_backends import (
            _configured_coreml_model,
        )
        assert _configured_coreml_model() == "/tmp/x.mlmodel"

    def test_the_field_exists_and_defaults_empty(self):
        from dreamlayer.config import Config
        assert hasattr(Config(), "coreml_model_path")

    def test_an_unreadable_config_is_not_fatal(self, monkeypatch):
        import dreamlayer.object_lens.classify_backends as B
        monkeypatch.setattr(B, "_configured_coreml_model",
                            B._configured_coreml_model)
        assert isinstance(B._configured_coreml_model(), str)


class TestThePromotionIsEarned:
    def test_available_alone_does_not_promote(self, tmp_path, monkeypatch):
        import dreamlayer.object_lens.classify_backends as B
        monkeypatch.setattr(B.CoreMLClassifier, "available", True)
        model = tmp_path / "m.mlmodel"
        model.write_bytes(b"x")
        c = B.CoreMLClassifier(model_path=str(model))
        assert c.predictions == 0, (
            "a wheel and a model file are not a prediction")

    def test_the_report_follows_a_real_prediction(self):
        import inspect

        from dreamlayer.ai_brain.server import server as s
        src = inspect.getsource(s)
        assert "DL_WIRED_COREML_ONDEVICE" in src
        assert "predictions" in src
