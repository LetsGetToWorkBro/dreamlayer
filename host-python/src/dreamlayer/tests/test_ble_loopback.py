"""Rig 0 — BLE framing loopback: Python bytes through the REAL Lua reassembler.

The framing layer had two latent interop defects that 1,800 tests never saw,
because Python framing and Lua reassembly were only ever tested against
themselves:

  1. real_bridge sent small (<= MTU) frames with NO length header while
     protocol.lua implements exactly one shape — length-prefixed. The first
     bytes of the JSON would be read as a garbage 32-bit length.
  2. real_bridge's multi-frame header excluded the 4 header bytes while
     protocol.lua's total INCLUDES them — truncating every large frame's
     last 4 bytes.

This suite drives real_bridge.frame_payload/chunk_frame output through the
real halo-lua/ble/protocol.lua under lupa, fuzzing sizes and fragmentation,
so the wire contract can never silently fork again.
"""
import json
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

lupa = pytest.importorskip("lupa")

from dreamlayer.bridge.real_bridge import (  # noqa: E402
    _MAX_FRAME_BYTES, _MTU_PAYLOAD_BYTES, chunk_frame, frame_payload,
)
from dreamlayer.reality_compiler.v2 import transport  # noqa: E402

HALO_LUA = Path(__file__).resolve().parents[4] / "halo-lua"


def make_protocol():
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{HALO_LUA}/?.lua;" .. package.path')
    proto = rt.eval('require("ble.protocol")')
    if isinstance(proto, tuple):        # require returns (module, path)
        proto = proto[0]
    return rt, proto


def feed_bytes(proto, data: bytes):
    """Feed raw bytes, returning every completed frame (drained).

    Pass Python bytes, never str: lupa UTF-8-encodes str on the way into
    Lua, which mangles header bytes > 127; bytes cross byte-exact.
    """
    out = []
    payload = proto["feed"](data)
    while payload is not None:
        out.append(payload.encode("utf-8") if isinstance(payload, str)
                   else bytes(payload))
        payload = proto["feed"](b"")
    return out


@pytest.fixture()
def proto():
    return make_protocol()[1]


class TestFramingContract:
    def test_small_frame_has_header(self):
        """The headerless small-frame shape must not exist on this wire."""
        framed = frame_payload({"t": "command", "kind": "wake"})
        total = int.from_bytes(framed[:4], "big")
        assert total == len(framed)

    def test_matches_v2_transport_framing(self):
        obj = {"t": "figment_swap", "id": "fig-1"}
        assert frame_payload(obj) == transport.frame(obj)

    def test_small_frame_reassembles(self, proto):
        obj = {"t": "command", "kind": "wake", "payload": {}}
        frames = feed_bytes(proto, frame_payload(obj))
        assert [json.loads(f) for f in frames] == [obj]

    def test_large_frame_reassembles_exactly(self, proto):
        """The last 4 bytes used to be truncated by the off-by-header bug."""
        obj = {"t": "card", "payload": {"text": "x" * 900}}
        framed = frame_payload(obj)
        collected = b""
        decoded = []
        for chunk in chunk_frame(framed):
            assert len(chunk) <= _MTU_PAYLOAD_BYTES
            collected += chunk
            for f in feed_bytes(proto, chunk):
                decoded.append(json.loads(f))
        assert collected == framed
        assert decoded == [obj]

    def test_oversize_frame_refused_host_side(self):
        with pytest.raises(ValueError):
            frame_payload({"t": "card", "payload": {"x": "y" * _MAX_FRAME_BYTES}})


class TestReassemblerDefense:
    def test_two_frames_in_one_chunk_both_drain(self, proto):
        a = frame_payload({"t": "command", "kind": "a"})
        b = frame_payload({"t": "command", "kind": "b"})
        frames = feed_bytes(proto, a + b)
        assert [json.loads(f)["kind"] for f in frames] == ["a", "b"]

    def test_garbage_header_drops_and_recovers(self, proto):
        # A huge bogus length must not wedge the link buffering forever.
        bogus = (10**9).to_bytes(4, "big") + b'{"t":"junk"}'
        assert feed_bytes(proto, bogus) == []
        assert proto["stats"]()["dropped"] == 1
        # The link recovers: the next well-formed frame decodes.
        obj = {"t": "command", "kind": "after"}
        assert [json.loads(f) for f in feed_bytes(proto, frame_payload(obj))] == [obj]

    def test_tiny_header_drops(self, proto):
        assert feed_bytes(proto, (2).to_bytes(4, "big") + b"xx") == []
        assert proto["stats"]()["dropped"] == 1

    def test_buffer_never_exceeds_max_frame_wait(self, proto):
        # While a legal frame is in flight the reassembler buffers at most
        # MAX_FRAME bytes — feed a max-size frame one byte at a time.
        body = json.dumps({"t": "card", "pad": "p" * 8000},
                          separators=(",", ":")).encode()
        framed = (len(body) + 4).to_bytes(4, "big") + body
        got = []
        for i in range(len(framed)):
            got += feed_bytes(proto, framed[i:i + 1])
        assert len(got) == 1 and json.loads(got[0])["t"] == "card"


class TestFramingProperty:
    @settings(max_examples=60, deadline=None)
    @given(
        text=st.text(
            alphabet=st.characters(codec="utf-8",
                                   blacklist_categories=("Cs",)),  # type: ignore[arg-type]
            max_size=2000),
        chunk_size=st.integers(min_value=1, max_value=400),
    )
    def test_roundtrip_any_payload_any_fragmentation(self, text, chunk_size):
        obj = {"t": "card", "payload": {"text": text}}
        framed = frame_payload(obj)
        rt, proto = make_protocol()
        decoded = []
        for chunk in chunk_frame(framed, chunk_size):
            for f in feed_bytes(proto, chunk):
                decoded.append(json.loads(f))
        assert decoded == [obj]

    @settings(max_examples=30, deadline=None)
    @given(objs=st.lists(
        st.fixed_dictionaries({"t": st.just("command"),
                               "kind": st.text(max_size=40)}),
        min_size=1, max_size=6))
    def test_back_to_back_frames_never_bleed(self, objs):
        stream = b"".join(frame_payload(o) for o in objs)
        rt, proto = make_protocol()
        decoded = [json.loads(f) for f in feed_bytes(proto, stream)]
        assert decoded == objs


class TestBleChaos:
    """Adversarial transport conditions — the storms a real radio produces."""

    @settings(max_examples=40, deadline=None)
    @given(
        objs=st.lists(
            st.fixed_dictionaries({"t": st.just("card"),
                                   "n": st.integers(min_value=0, max_value=9999)}),
            min_size=1, max_size=8),
        seed=st.integers(min_value=0, max_value=10_000),
    )
    def test_random_refragmentation_recovers_every_frame(self, objs, seed):
        # concatenate all frames, then cut the stream at arbitrary boundaries —
        # the reassembler must recover every object regardless of where chunks split
        stream = b"".join(frame_payload(o) for o in objs)
        rt, proto = make_protocol()
        i, decoded = 0, []
        import random
        rng = random.Random(seed)
        while i < len(stream):
            step = rng.randint(1, 40)
            for f in feed_bytes(proto, stream[i:i + step]):
                decoded.append(json.loads(f))
            i += step
        assert decoded == objs

    def test_garbage_interleaved_between_good_frames_recovers(self):
        rt, proto = make_protocol()
        good1 = frame_payload({"t": "command", "kind": "a"})
        good2 = frame_payload({"t": "command", "kind": "b"})
        garbage = (10**9).to_bytes(4, "big")            # a bogus huge length
        decoded = []
        for f in feed_bytes(proto, good1):
            decoded.append(json.loads(f))
        # a garbage header lands mid-stream → dropped, link recovers
        feed_bytes(proto, garbage)
        for f in feed_bytes(proto, good2):
            decoded.append(json.loads(f))
        assert [d["kind"] for d in decoded] == ["a", "b"]
        assert proto["stats"]()["dropped"] >= 1

    def test_reset_mid_stream_discards_partial_then_resyncs(self):
        # a disconnect drops a half-received frame; reset() clears it and the
        # next full frame after reconnect decodes cleanly (no bleed from the
        # truncated one)
        rt, proto = make_protocol()
        framed = frame_payload({"t": "card", "payload": {"text": "x" * 400}})
        half = framed[: len(framed) // 2]
        assert feed_bytes(proto, half) == []            # partial, nothing yet
        proto["reset"]()                                # "disconnect"
        obj = {"t": "command", "kind": "after-reconnect"}
        decoded = [json.loads(f) for f in feed_bytes(proto, frame_payload(obj))]
        assert decoded == [obj]

    def test_duplicate_frames_both_deliver(self):
        # BLE can re-deliver; the framing layer is not a dedup layer, so both
        # copies decode (idempotency is the app's job, and this documents that)
        rt, proto = make_protocol()
        f = frame_payload({"t": "TEL", "event": "CARD_SHOWN"})
        decoded = [json.loads(x) for x in feed_bytes(proto, f + f)]
        assert len(decoded) == 2

    def test_oversize_length_never_buffers_unbounded(self):
        # the cap is the whole point: a giant advertised length is dropped at
        # the header, not buffered toward MAX_FRAME
        rt, proto = make_protocol()
        feed_bytes(proto, (_MAX_FRAME_BYTES + 1).to_bytes(4, "big") + b"junk")
        assert proto["stats"]()["dropped"] == 1
        obj = {"t": "command", "kind": "ok"}
        assert [json.loads(f) for f in feed_bytes(proto, frame_payload(obj))] == [obj]
