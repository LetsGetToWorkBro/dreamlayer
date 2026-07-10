"""Perception regression — a real pixel-reading classifier held to an accuracy
floor on synthetic-but-genuine images.

Unlike a statistics-to-index mock, HeuristicVisionClassifier extracts actual
image features (brightness, saturation, greenness, warmth, edge density) and
labels by nearest prototype. The generators below paint real pixels with those
properties — a leafy green field, a page of dark text on paper, a dark screen
with a couple of UI bars, a smooth warm vessel — and the test asserts the
classifier recovers the labels. That exercises the whole feature-extraction and
classification path end to end in CI, with no ML deps. The real neural backends
(CLIP/moondream/YOLO) are held to their own floor in the real-models job."""
import numpy as np
import pytest

from dreamlayer.object_lens.classify_backends import (
    HeuristicVisionClassifier,
    default_classifier,
)
from dreamlayer.object_lens.recognizer import ObjectRecognizer

SIZE = 64


def _plant(rng):
    img = np.zeros((SIZE, SIZE, 3), np.float32)
    img[..., 0], img[..., 1], img[..., 2] = 40, 150, 50   # green-dominant
    img += rng.normal(0, 26, img.shape)                    # leafy texture → edges
    return np.clip(img, 0, 255).astype(np.uint8)


def _book(rng):
    img = np.full((SIZE, SIZE, 3), 225, np.float32)        # bright paper
    img[..., 2] -= 18                                      # slightly warm/cream
    for r in range(4, SIZE, 4):                            # rows of dark "text"
        img[r:r + 1, 6:SIZE - 6, :] = 20
    img += rng.normal(0, 5, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def _screen(rng):
    img = np.full((SIZE, SIZE, 3), 45, np.float32)         # dark, desaturated
    img[10:12, :, :] = 90                                  # a couple of UI bars
    img[30:32, :, :] = 80
    img += rng.normal(0, 6, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def _mug(rng):
    img = np.zeros((SIZE, SIZE, 3), np.float32)
    img[..., 0], img[..., 1], img[..., 2] = 205, 110, 55   # warm, saturated
    img += rng.normal(0, 6, img.shape)                     # smooth → low edges
    return np.clip(img, 0, 255).astype(np.uint8)


GENERATORS = {
    "houseplant": _plant,
    "book": _book,
    "screen": _screen,
    "mug": _mug,
}


def _dataset(n_per_class=8):
    rng = np.random.default_rng(1234)     # fixed seed → deterministic suite
    samples = []
    for label, gen in GENERATORS.items():
        for _ in range(n_per_class):
            samples.append((label, gen(rng)))
    return samples


class TestHeuristicVision:
    def test_accuracy_floor(self):
        clf = HeuristicVisionClassifier()
        samples = _dataset()
        correct = 0
        for label, img in samples:
            out = clf(img)
            if out is not None and out[0] == label:
                correct += 1
        acc = correct / len(samples)
        assert acc >= 0.85, f"heuristic vision accuracy regressed to {acc:.2f}"

    def test_blank_frame_declines(self):
        clf = HeuristicVisionClassifier()
        flat = np.full((SIZE, SIZE, 3), 60, np.uint8)
        assert clf(flat) is None

    def test_confidence_in_unit_range(self):
        clf = HeuristicVisionClassifier()
        for _label, img in _dataset(n_per_class=2):
            out = clf(img)
            assert out is None or (0.0 <= out[1] <= 1.0)

    def test_it_is_the_offline_base_rung(self):
        # with no neural deps installed, the ladder now returns a real
        # pixel-reading classifier rather than None.
        clf = default_classifier()
        assert isinstance(clf, HeuristicVisionClassifier)
        clf_off = default_classifier(heuristic_fallback=False)
        assert clf_off is None or callable(clf_off)

    def test_flows_through_the_recognizer(self):
        # the classifier satisfies the ObjectRecognizer seam contract end to end
        rec = ObjectRecognizer(classify_fn=HeuristicVisionClassifier(),
                               min_confidence=0.5)
        rng = np.random.default_rng(7)
        sighting = rec.recognize(_plant(rng))
        assert sighting is not None and sighting.label == "houseplant"


class TestRealVisionInference:
    @pytest.mark.real_model
    def test_clip_runs_real_inference(self):
        # Runs for real in the real-models CI job (open_clip + torch installed).
        # Synthetic noise fields aren't photographs, so we don't pin the label —
        # we assert the real model loads, runs, and returns a well-formed pick
        # from the label set with a calibrated confidence.
        from dreamlayer.object_lens.classify_backends import ClipClassifier
        if not ClipClassifier.available:
            pytest.skip("open_clip not installed")
        labels = ["a green houseplant", "a page of text",
                  "a computer screen", "a coffee mug"]
        clf = ClipClassifier(labels)
        rng = np.random.default_rng(3)
        out = clf(_plant(rng))
        assert out is not None
        label, conf = out
        assert label in labels and 0.0 <= conf <= 1.0
