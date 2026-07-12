"""BLE frame codec: JSON stays the byte-exact device default; CBOR is an
optional compact, self-describing body that auto-detects on parse. cbor2 is
installable, so the CBOR path is really exercised (importorskip)."""
import json

import pytest

from dreamlayer.reality_compiler.v2 import transport as T

ENV = {"t": "figment_text", "id": "abc123", "text": "hola mundo",
       "slot": "translation"}
BIG = {"t": "figment_put", "id": "lens42",
       "figment": {"name": "Rosetta", "scenes": {"a": {"lines": [
           {"content": "{slot:translation}", "row": 1, "size": "md",
            "color": "text_primary"}]}}}}


class TestJsonUnchanged:
    def test_default_is_json_and_byte_exact(self):
        f = T.frame(ENV)
        # header + canonical JSON body, exactly the device wire
        body = json.dumps(ENV, sort_keys=True, separators=(",", ":")).encode()
        assert f == (len(body) + 4).to_bytes(4, "big") + body
        assert T.parse_frame(f) == ENV

    def test_json_body_starts_with_brace(self):
        assert T.frame(ENV)[4:5] == b"{"


class TestCborCodec:
    def setup_method(self):
        pytest.importorskip("cbor2")

    def test_roundtrips(self):
        assert T.parse_frame(T.frame(ENV, codec="cbor")) == ENV
        assert T.parse_frame(T.frame(BIG, codec="cbor")) == BIG

    def test_cbor_is_smaller_on_the_wire(self):
        assert len(T.frame(BIG, codec="cbor")) < len(T.frame(BIG))

    def test_first_body_byte_is_a_cbor_map(self):
        first = T.frame(ENV, codec="cbor")[4]
        assert 0xA0 <= first <= 0xBF

    def test_parse_auto_detects_both(self):
        # a reader with no codec hint handles either frame
        assert T.parse_frame(T.frame(ENV)) == ENV                 # json
        assert T.parse_frame(T.frame(ENV, codec="cbor")) == ENV   # cbor

    def test_length_header_still_validated(self):
        f = bytearray(T.frame(ENV, codec="cbor"))
        f[0] = 0xFF                       # corrupt the length header
        with pytest.raises(ValueError):
            T.parse_frame(bytes(f))


class TestCborUnavailable:
    def test_encode_requires_cbor2(self, monkeypatch):
        monkeypatch.setattr(T, "_HAS_CBOR", False)
        with pytest.raises(RuntimeError):
            T.frame(ENV, codec="cbor")
