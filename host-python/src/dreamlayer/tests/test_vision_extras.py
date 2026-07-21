"""On-demand perception adapters (math OCR, doc layout, depth, open-vocab find,
segment) + the GLiNER commitment enhancer. None of the wheels are in CI, so
these pin the graceful-fallback contract and the capability registrations.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.object_lens import vision_extras as V
from dreamlayer.social_lens.commitment_ner import GlinerCommitments, default_commitment_ner
from dreamlayer.social_lens.meeting import MeetingLog


def _frame():
    f = np.zeros((16, 16, 3), np.uint8)
    f[::2] = 180
    return f


class TestFrameCoercion:
    def test_shapes_and_junk(self):
        assert V._np_image(np.zeros((8, 8), np.uint8)).shape == (8, 8, 3)
        assert V._np_image(np.zeros((8, 8, 4), np.uint8)).shape == (8, 8, 3)
        assert V._np_image(object()) is None


class TestFallbacks:
    def test_math_ocr(self):
        r = V.MathOcrReader()
        assert r.read_math(_frame()) == ""            # no pix2tex → "" (never raises)

    def test_doc_read(self):
        assert V.DocReader().read_doc(_frame()) == {}

    def test_depth(self):
        assert V.DepthReader().nearest_relative(_frame()) is None

    def test_find(self):
        f = V.YoloWorldFinder()
        assert f.find(_frame(), ["keys"]) is None
        assert f.find(_frame(), []) is None            # no terms → None

    def test_segment(self):
        assert V.FastSamSegmenter().segment(_frame()) is None


class TestGliner:
    def test_fallback_is_empty(self):
        g = GlinerCommitments()
        assert g.ready is False
        assert g.extract("I'll send the deck Friday") == []
        assert g.extract("") == []

    def test_default_is_none_without_the_wheel(self):
        assert default_commitment_ner() is None

    def test_meeting_merges_ner_actions(self, tmp_path):
        # a fake NER injects a commitment the deterministic pass would miss
        class FakeNer:
            def extract(self, text):
                return [{"text": "owner Dana ships the build", "when": "EOW"}]
        log = MeetingLog(tmp_path / "m.json", ner=FakeNer())
        log.start()
        live = log.note("we synced on scope")           # no regex action here
        texts = [a["text"] for a in live["actions"]]
        assert "owner Dana ships the build" in texts

    def test_a_raising_ner_never_breaks_a_note(self, tmp_path):
        class BoomNer:
            def extract(self, text):
                raise RuntimeError("ner down")
        log = MeetingLog(tmp_path / "m.json", ner=BoomNer())
        log.start()
        assert log.note("I'll book the room Monday") is not None   # deterministic still works


def test_perception_capabilities_registered():
    from dreamlayer import capabilities as C
    keys = {c.key: c for c in C.CAPABILITIES}
    for k, extra, mod in [
        ("math_ocr", "math-ocr", "pix2tex"),
        ("doc_read", "doc-ocr", "surya"),
        ("depth_sense", "depth", "transformers"),
        ("openvocab_find", "vision", "ultralytics"),
        ("scene_segment", "vision", "ultralytics"),
        ("commitment_ner", "nlp-extra", "gliner"),
    ]:
        assert k in keys, f"missing cap {k}"
        assert keys[k].extra == extra
        assert mod in keys[k].modules
