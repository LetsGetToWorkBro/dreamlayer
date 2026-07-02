from dreamlayer.bridge.emulator_bridge import EmulatorBridge

def test_lifecycle():
    b = EmulatorBridge()
    info = b.connect()
    assert info["lua"] == "5.3"
    assert info["display"] == [256, 256]
    assert b.state == "ready"
    b.disconnect()
    assert b.state == "sleeping"

def test_paused_blocks_content_card():
    b = EmulatorBridge(); b.connect()
    b.inject_event("privacy_pause")
    assert b.state == "paused"
    b.send_card({"type": "ObjectRecallCard", "primary": "Keys"})
    assert b.last_card["type"] == "PrivacyVeilCard"

def test_privacy_card_always_passes_through():
    b = EmulatorBridge(); b.connect()
    b.inject_event("privacy_pause")
    b.send_card({"type": "PrivacyVeilCard", "primary": "Privacy Veil"})
    assert b.last_card["type"] == "PrivacyVeilCard"

def test_resume_allows_content():
    b = EmulatorBridge(); b.connect()
    b.inject_event("privacy_pause")
    b.inject_event("privacy_resume")
    assert b.state == "ready"
    b.send_card({"type": "ObjectRecallCard", "primary": "Wallet"})
    assert b.last_card["type"] == "ObjectRecallCard"

def test_event_callback_fires():
    b = EmulatorBridge(); b.connect()
    received = []
    b.on_event(lambda n, p: received.append(n))
    b.inject_event("privacy_pause")
    assert "privacy_pause" in received

def test_lua_bundle_requires_main():
    import os, tempfile, pytest
    from dreamlayer.bridge.lua_loader import collect_lua
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(FileNotFoundError, match="main.lua"):
            collect_lua(d)

def test_lua_bundle_collects_all():
    import os
    here = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "halo-lua"))
    if not os.path.isdir(here):
        return
    from dreamlayer.bridge.lua_loader import collect_lua
    bundle = collect_lua(here)
    assert "main.lua" in bundle
    assert len(bundle) >= 20
