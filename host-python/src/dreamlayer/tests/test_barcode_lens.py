"""Barcode decode → Open Food Facts → DietaryProfile.

zxing-cpp isn't a CI dep, so the decoder pins the absent-wheel no-op; the OFF
lookup + provider run fully offline through injected seams. The load-bearing
checks: the code is sanitized before it ever builds a URL, the lookup is cached,
the Veil keeps the lookup from firing, and an allergen you avoid surfaces.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.object_lens import barcode_backends as B
from dreamlayer.object_lens.barcode_lens import BarcodeFoodProvider
from dreamlayer.object_lens.label import DietaryProfile
from dreamlayer.object_lens.recognizer import ObjectRecognizer
from dreamlayer.object_lens.schema import ObjectSighting
from dreamlayer.plugins import openfoodfacts as OFF


class TestDecoderFallback:
    def test_default_is_none_without_the_wheel(self):
        assert B.default_barcode_decoder() is None

    def test_reader_returns_none_when_unavailable(self):
        d = B.ZxingBarcodeDecoder()
        if not d.available:
            assert d(np.zeros((8, 8, 3), np.uint8)) is None

    def test_frame_coercion_and_gtin(self):
        assert B._to_image(np.zeros((4, 4), np.uint8)).shape == (4, 4, 3)
        assert B._to_image(object()) is None
        assert B.is_gtin("0123456789012") is True     # EAN-13
        assert B.is_gtin("01234567") is True           # EAN-8
        assert B.is_gtin("12-ab") is False
        assert B.is_gtin("1234567") is False           # 7 digits: too short


class TestOffBarcodeLookup:
    def test_query_is_sanitized_to_digits(self):
        url = OFF.build_barcode_query("  01 23-4567_89012 ")
        assert "/0123456789012.json" in url
        assert "allergens_tags" in url and "ingredients_text" in url

    def test_found_product_parses_allergens_and_ingredients(self):
        payload = ('{"status":1,"product":{"product_name":"Oat Bar",'
                   '"nutriscore_grade":"a","brands":"Acme",'
                   '"allergens_tags":["en:milk","en:soybeans"],'
                   '"ingredients_text":"oats, milk, soy lecithin"}}')
        out = OFF.lookup_by_barcode("0123456789012", lambda u: payload)
        assert out["product_name"] == "Oat Bar"
        assert out["nutriscore"] == "A"
        assert "milk" in out["allergens"] and "soybeans" in out["allergens"]
        assert "soy lecithin" in out["ingredients"]

    def test_unknown_product_is_empty(self):
        out = OFF.lookup_by_barcode("0123456789012", lambda u: '{"status":0}')
        assert out == {}

    def test_non_gtin_never_fetches(self):
        called = []
        OFF.lookup_by_barcode("12", lambda u: called.append(u) or "{}")
        assert called == []                            # too short → no egress

    def test_cache_holds_within_ttl(self):
        calls = []
        clock = [1000.0]
        payload = '{"status":1,"product":{"nutriscore_grade":"b"}}'
        fn = OFF.off_barcode_fn(lambda u: calls.append(u) or payload,
                                ttl=300.0, now_fn=lambda: clock[0])
        assert fn("0123456789012")["nutriscore"] == "B"
        assert fn("01 2345 678 9012")["nutriscore"] == "B"   # same digits → cached
        assert len(calls) == 1

    def test_string_or_int_status_both_count_as_found(self):
        for st in ("1", 1):
            out = OFF.lookup_by_barcode(
                "0123456789012",
                lambda u, s=st: '{"status": %s, "product": {"nutriscore_grade":"a"}}'
                % ('"1"' if s == "1" else "1"))
            assert out.get("nutriscore") == "A"

    def test_cache_is_bounded(self):
        # a stream of DISTINCT barcodes can't grow the cache without limit — the
        # oldest is evicted, proven by the first key needing a re-fetch
        calls = []
        fn = OFF.off_barcode_fn(lambda u: calls.append(u) or '{"status":0}',
                                ttl=9e9, now_fn=lambda: 0.0, maxsize=8)
        first = "1000000000000"
        fn(first)                                    # cached
        for i in range(1, 20):                       # 19 more distinct → evicts oldest
            fn(f"{1000000000000 + i}")
        n = len(calls)
        fn(first)                                    # evicted → must re-fetch
        assert len(calls) == n + 1


class TestRecognizerAttachesBarcode:
    def _frame(self):
        f = np.zeros((32, 32, 3), np.uint8)
        f[::2] = 200
        return f

    def test_barcode_lands_in_attributes(self):
        rec = ObjectRecognizer(classify_fn=lambda f: ("box", 0.9, {}),
                               barcode_fn=lambda f: [("EAN13", "0123456789012")])
        s = rec.recognize(self._frame())
        assert s.attributes["barcode"] == "0123456789012"

    def test_gtin_is_preferred_over_a_qr_payload(self):
        rec = ObjectRecognizer(
            classify_fn=lambda f: ("box", 0.9, {}),
            barcode_fn=lambda f: [("QRCODE", "https://x"), ("EAN13", "4006381333931")])
        s = rec.recognize(self._frame())
        assert s.attributes["barcode"] == "4006381333931"

    def test_no_decode_leaves_the_look_clean(self):
        rec = ObjectRecognizer(classify_fn=lambda f: ("box", 0.9, {}),
                               barcode_fn=lambda f: None)
        s = rec.recognize(self._frame())
        assert "barcode" not in s.attributes


class TestBarcodeFoodProvider:
    def _sighting(self, code="0123456789012"):
        return ObjectSighting(label="snack bar", confidence=0.9,
                              attributes={"barcode": code})

    def _provider(self, profile, product, allow=True):
        return BarcodeFoodProvider(profile, lookup_fn=lambda code: product,
                                   allow_network=lambda: allow)

    def test_matches_only_with_a_barcode(self):
        p = BarcodeFoodProvider(DietaryProfile(), lookup_fn=lambda c: {})
        assert p.matches(self._sighting()) is True
        assert p.matches(ObjectSighting(label="mug", confidence=0.9,
                                        attributes={})) is False

    def test_avoided_allergen_surfaces(self):
        prof = DietaryProfile(avoid={"dairy"})
        product = {"product_name": "Oat Bar", "nutriscore": "A",
                   "allergens": ["milk", "soybeans"],
                   "ingredients": "oats, milk, soy"}
        rows = self._provider(prof, product).build(self._sighting())
        labels = [r.label for r in rows]
        assert "contains" in labels
        assert any(r.label == "⚠ you avoid" and r.detail == "dairy" for r in rows)
        assert any(r.label == "Nutri-Score" and r.value == "A" for r in rows)

    def test_no_avoided_allergen_stays_calm(self):
        prof = DietaryProfile(avoid={"gluten"})
        product = {"allergens": ["milk"], "ingredients": "oats, milk"}
        rows = self._provider(prof, product).build(self._sighting())
        assert not any(r.label == "⚠ you avoid" for r in rows)

    def test_veil_up_blocks_the_lookup(self):
        calls = []
        p = BarcodeFoodProvider(DietaryProfile(avoid={"dairy"}),
                                lookup_fn=lambda c: calls.append(c) or {"allergens": ["milk"]},
                                allow_network=lambda: False)
        assert p.build(self._sighting()) == []
        assert calls == []                             # no egress under the Veil

    def test_a_raising_gate_fails_closed(self):
        def boom():
            raise RuntimeError("gate on fire")
        p = BarcodeFoodProvider(DietaryProfile(), lookup_fn=lambda c: {"allergens": ["x"]},
                                allow_network=boom)
        assert p.build(self._sighting()) == []         # can't confirm allowed → don't send

    def test_empty_product_emits_nothing(self):
        rows = self._provider(DietaryProfile(), {}).build(self._sighting())
        assert rows == []

    def test_default_gate_fails_closed(self):
        # a provider built with NO allow_network gate must NOT egress (fail
        # closed — a forgotten gate can't leak; audit fix)
        calls = []
        p = BarcodeFoodProvider(DietaryProfile(avoid={"dairy"}),
                                lookup_fn=lambda c: calls.append(c) or {"allergens": ["milk"]})
        assert p.build(self._sighting()) == []
        assert calls == []


def test_barcode_scan_capability_registered():
    from dreamlayer import capabilities as C
    cap = next((c for c in C.CAPABILITIES if c.key == "barcode_scan"), None)
    assert cap is not None
    assert cap.extra == "vision"
    assert cap.modules == ("zxingcpp",)
    assert cap.seam == "object_lens/barcode_backends.py"
