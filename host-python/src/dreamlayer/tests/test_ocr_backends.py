"""On-device OCR reader + its recognizer enrichment.

RapidOCR isn't installed in CI, so these pin the contract: absent the wheel it's
a clean "" no-op; the frame coercion is forgiving; and — the load-bearing part —
every OCR line is person- and PII-scrubbed before it can surface, then the read
text lands in attributes["text"] where Rosetta / taste / price providers read it.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.object_lens import ocr_backends as O
from dreamlayer.object_lens.recognizer import ObjectRecognizer


class TestFallback:
    def test_default_ocr_is_none_without_the_wheel(self):
        # rapidocr-onnxruntime is not a CI dep → no reader, callers add no text
        assert O.default_ocr() is None

    def test_reader_returns_empty_when_unavailable(self):
        r = O.RapidOcrReader()
        if not r.available:                    # the CI path
            assert r(np.zeros((8, 8, 3), np.uint8)) == ""
            assert r.read_text(np.zeros((8, 8, 3), np.uint8)) == ""


class TestFrameCoercion:
    def test_grayscale_and_rgba_and_float(self):
        assert O._to_ocr_image(np.zeros((4, 4), np.uint8)).shape == (4, 4, 3)
        assert O._to_ocr_image(np.zeros((4, 4, 4), np.uint8)).shape == (4, 4, 3)
        f = O._to_ocr_image(np.ones((4, 4, 3), np.float32))   # 0..1 float → uint8
        assert f.dtype == np.uint8 and int(f.max()) == 255

    def test_pil_image_is_accepted(self):
        from PIL import Image
        img = Image.new("RGB", (5, 5), (10, 20, 30))
        assert O._to_ocr_image(img).shape == (5, 5, 3)

    def test_junk_is_none_not_a_crash(self):
        assert O._to_ocr_image(object()) is None


class TestPrivacyScrub:
    """The one guarantee OCR owns: it never emits a stranger's name or a
    contact detail. person_guard's deterministic name-shape layer is always on,
    so these hold with no optional deps installed."""

    def test_a_person_named_line_is_dropped(self):
        assert O._keep_line("Maya Chen") is False          # given + family → a person
        assert O._keep_line("Dr. Robert Langdon") is False

    def test_contact_detail_lines_are_dropped(self):
        assert O._keep_line("maya@example.com") is False
        assert O._keep_line("call 555-123-4567") is False
        assert O._keep_line("(555) 123-4567") is False
        assert O._keep_line("+1 555 123 4567") is False

    def test_isbns_and_prices_are_kept_not_scrubbed_as_phones(self):
        # the old \d{7,15} phone rule swallowed every ISBN — a headline OCR
        # target; a bare digit run must now survive (audit fix)
        assert O._keep_line("9780306406157") is True     # ISBN-13
        assert O._keep_line("0306406152") is True        # ISBN-10
        assert O._keep_line("978-0-306-40615-7") is True # hyphenated ISBN
        assert O._keep_line("$4.95") is True

    def test_ordinary_world_text_is_kept(self):
        assert O._keep_line("Chardonnay 2019 $12") is True
        assert O._keep_line("PLATFORM 9") is True
        assert O._keep_line("") is False


class TestRecognizerEnrichment:
    """attributes["text"] is the channel Rosetta translation, the taste lens,
    and the currency/pokemon/vinyl providers consume — OCR fills it for real."""

    def _frame(self):
        # textured frame so the deterministic mock/heuristic yields a sighting
        rng = np.zeros((32, 32, 3), np.uint8)
        rng[::2] = 200
        return rng

    def test_ocr_text_lands_in_attributes(self):
        rec = ObjectRecognizer(classify_fn=lambda f: ("bottle", 0.9, {}),
                               ocr_fn=lambda f: "Chardonnay 2019 $12")
        s = rec.recognize(self._frame())
        assert s is not None
        assert s.attributes["text"] == "Chardonnay 2019 $12"

    def test_ocr_is_ground_truth_over_a_vlm_guess(self):
        rec = ObjectRecognizer(
            classify_fn=lambda f: ("menu", 0.9, {"text": "blurry guess"}),
            ocr_fn=lambda f: "Latte 4.50")
        s = rec.recognize(self._frame())
        assert s.attributes["text"] == "Latte 4.50"

    def test_no_ocr_leaves_the_look_untouched(self):
        rec = ObjectRecognizer(classify_fn=lambda f: ("mug", 0.9, {}),
                               ocr_fn=lambda f: "")
        s = rec.recognize(self._frame())
        assert "text" not in s.attributes

    def test_a_name_reassembled_across_lines_is_dropped_at_the_boundary(self):
        # a badge renders "Maya" and "Chen" as separate regions; each passes the
        # per-line shape rule, but the recognizer re-gates the JOINED text so the
        # reassembled name never reaches attributes["text"] (audit fix)
        rec = ObjectRecognizer(classify_fn=lambda f: ("lanyard", 0.9, {}),
                               ocr_fn=lambda f: "Maya Chen")
        s = rec.recognize(self._frame())
        assert "text" not in s.attributes

    def test_a_raising_ocr_guard_drops_the_text(self, monkeypatch):
        # the boundary gate fails CLOSED: if person_guard raises on the OCR text,
        # drop it. (Raise only for the OCR string so the earlier label check —
        # which calls the same guard — is unaffected.)
        import dreamlayer.object_lens.person_guard as pg
        orig = pg.defers_person

        def flaky(label, frame=None):
            if label == "anything at all":
                raise RuntimeError("boom")
            return orig(label, frame)
        monkeypatch.setattr(pg, "defers_person", flaky)
        rec = ObjectRecognizer(classify_fn=lambda f: ("sign", 0.9, {}),
                               ocr_fn=lambda f: "anything at all")
        s = rec.recognize(self._frame())
        assert "text" not in s.attributes

    def test_a_person_look_never_reaches_ocr(self):
        # a person label defers to the Social Lens BEFORE OCR runs — proven by
        # an ocr_fn that would explode if it were ever called
        def boom(_f):
            raise AssertionError("OCR must not run on a person")
        rec = ObjectRecognizer(classify_fn=lambda f: ("Sarah Miller", 0.9, {}),
                               ocr_fn=boom)
        assert rec.recognize(self._frame()) is None


def test_text_ocr_capability_registered():
    from dreamlayer import capabilities as C
    cap = next((c for c in C.CAPABILITIES if c.key == "text_ocr"), None)
    assert cap is not None
    assert cap.extra == "vision"
    assert cap.modules == ("rapidocr_onnxruntime",)
    assert cap.seam == "object_lens/ocr_backends.py"
