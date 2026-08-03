"""Privacy-hardening regression tests for the bridge display surfaces.

Written to FAIL ON REVERT: `RealBridge._on_inbound` must not echo the raw
(possibly signal-derived) frame back into the event stream when parsing fails.

The three `FrameDisplay` cases that used to sit above this were deleted with
`bridge/frame_sdk.py` — a display adapter for a DIFFERENT manufacturer's device
(Brilliant Labs Frame) that this product is not built for. The chokepoint they
guarded is the one `real_bridge.send_card` holds, and that is tested against the
bridge the glasses actually use.
"""
from dreamlayer.bridge.real_bridge import RealBridge


def test_real_bridge_parse_error_omits_raw_frame():
    """An inbound parse failure must emit an error marker WITHOUT the raw bytes.

    FAILS ON REVERT: the old code attached ``"raw": str(raw)`` to the event, so
    the distinctive signal-marker below would appear in the emitted payload.
    """
    b = RealBridge()
    events = []
    b.on_event(lambda name, payload: events.append((name, payload)))

    # Stand-in for signal-derived (mic/camera) content that fails to parse.
    raw = "RAW_SIGNAL_BYTES_DO_NOT_LEAK {not-valid-json"
    b._on_inbound(raw)

    assert len(events) == 1
    name, payload = events[0]
    assert name == "parse_error"
    assert "raw" not in payload
    assert not any(
        "RAW_SIGNAL_BYTES_DO_NOT_LEAK" in str(v) for v in payload.values()
    ), "raw frame content leaked into the parse_error event"
