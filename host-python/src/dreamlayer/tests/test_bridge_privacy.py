"""Privacy-hardening regression tests for the bridge display surfaces.

Each test here is written to FAIL ON REVERT of its corresponding fix:

  * FrameDisplay.show_card must not light the display with a content card
    while the veil is up (mirrors real_bridge.send_card's chokepoint).
  * RealBridge._on_inbound must not echo the raw (possibly signal-derived)
    frame back into the event stream when parsing fails.
"""
from dreamlayer.bridge.frame_sdk import FrameDisplay
from dreamlayer.bridge.real_bridge import RealBridge
from dreamlayer.memory.privacy import PrivacyGate


# ---------------------------------------------------------------------------
# Item 1 — FrameDisplay.show_card privacy chokepoint
# ---------------------------------------------------------------------------

def test_frame_display_suppresses_content_card_while_paused():
    """A content card must not reach the display while the veil is up.

    FAILS ON REVERT: without the gate, show_card records/shows every card, so
    the suppressed content card would appear in ``sent``.
    """
    gate = PrivacyGate()
    gate.pause()
    disp = FrameDisplay(privacy=gate)
    disp.show_card({
        "type": "ObjectRecallCard",
        "title": "Keys",
        "answer": "hidden on the SECRET shelf",
    })
    assert disp.sent == [], "content card leaked past the pause veil"
    assert not any("SECRET" in str(entry) for entry in disp.sent)


def test_frame_display_privacy_veil_card_passes_while_paused():
    """The PrivacyVeilCard itself must still light the display while paused."""
    gate = PrivacyGate()
    gate.pause()
    disp = FrameDisplay(privacy=gate)
    disp.show_card({"type": "PrivacyVeilCard", "title": "Privacy Veil"})
    assert len(disp.sent) == 1
    assert disp.sent[0]["kind"] == "card"


def test_frame_display_default_gate_is_permissive():
    """No gate wired => permissive AlwaysOnGate(): content shows as before."""
    disp = FrameDisplay()
    disp.show_card({"type": "ObjectRecallCard", "title": "Keys", "answer": "shelf"})
    assert len(disp.sent) == 1


# ---------------------------------------------------------------------------
# Item 2 — RealBridge inbound parse-failure must not echo the raw frame
# ---------------------------------------------------------------------------

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
