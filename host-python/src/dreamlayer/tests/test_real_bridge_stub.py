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
