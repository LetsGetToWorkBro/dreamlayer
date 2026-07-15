import pytest
from dreamlayer.bridge.real_bridge import RealBridge

def test_connect_raises_without_sdk_or_hardware():
    b = RealBridge()
    with pytest.raises((ImportError, NotImplementedError, RuntimeError)):
        b.connect()

def test_inject_event_raises_for_unknown():
    b = RealBridge()
    with pytest.raises(NotImplementedError):
        b.inject_event("totally_fake_event")

def test_inject_known_event_raises_hardware_not_connected():
    b = RealBridge()
    with pytest.raises((NotImplementedError, RuntimeError, ImportError)):
        b.inject_event("privacy_pause")


# -- disconnect/reconnect resilience + no thread leak (audit 2026-07-14) -------

def test_disconnect_survives_a_dropped_link_and_reaps_the_thread():
    """A dropped BLE/socket link may make the SDK disconnect() raise; that must
    never crash the caller, and the daemon event-loop thread must be reclaimed
    (it used to leak for the process lifetime)."""
    b = RealBridge()

    class DroppedClient:
        async def disconnect(self):
            raise ConnectionError("link already down")

    b._client = DroppedClient()
    b.disconnect()                       # must NOT raise despite the dropped link
    assert b._client is None
    assert b._thread is None and b._loop is None   # thread reaped, not leaked


def test_disconnect_clean_path_reaps_the_thread():
    b = RealBridge()

    class OkClient:
        seen = False
        async def disconnect(self):
            OkClient.seen = True

    b._client = OkClient()
    b.disconnect()
    assert OkClient.seen is True
    assert b._client is None and b._thread is None


def test_disconnect_without_a_client_is_a_safe_noop():
    b = RealBridge()
    b.disconnect()                       # never connected — must not raise
    assert b._client is None and b._thread is None


def test_send_card_drops_content_while_paused():
    """The transport-level veil: a paused bridge delivers nothing but the veil
    card. A content card is dropped before it can reach the link."""
    b = RealBridge()
    sent = []

    class RecordingClient:
        async def send(self, msg):
            sent.append(msg)

    b._client = RecordingClient()
    with b._paused_lock:
        b._paused = True
    b.send_card({"type": "AnswerCard", "payload": {}})   # content → dropped
    assert sent == []                                    # never reached transport
