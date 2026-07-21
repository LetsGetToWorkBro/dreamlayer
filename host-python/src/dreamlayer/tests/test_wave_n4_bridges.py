"""Wave N4: Meshtastic bridge, Extism host, Immich/Home-Assistant/Dawarich
LAN services, Syncthing probe.

No radios, runtimes, or servers in CI — so these pin the fallback contracts,
the STRUCTURAL LAN-only gates (a public base URL disables a service source
outright), the pure home-alert policy, and payload parsing via fetch seams.
"""
from __future__ import annotations

import json

from dreamlayer.memory.source_dawarich import DawarichSource, default_dawarich
from dreamlayer.memory.source_immich import ImmichSource, default_immich
from dreamlayer.orchestrator.home_bridge import HomeBridge, default_home_bridge, home_alerts
from dreamlayer.orchestrator.mesh_bridge import MeshBridge, default_mesh
from dreamlayer.plugins.extism_host import ExtismHost, default_extism_host


class TestMesh:
    def test_fallback_without_wheel_or_radio(self):
        b = MeshBridge()
        if not MeshBridge.available:
            assert b.connect() is False
            assert default_mesh() is None
        assert b.ready is False
        assert b.send("hello") is False              # no radio → False, no raise

    def test_send_refuses_empty_and_truncates(self):
        b = MeshBridge()
        assert b.send("   ") is False

        class FakeIface:
            def __init__(self):
                self.sent = []

            def sendText(self, text, channelIndex=0):
                self.sent.append((text, channelIndex))
        b._iface = FakeIface()
        assert b.send("x" * 500, channel=2) is True
        text, ch = b._iface.sent[0]
        assert len(text.encode("utf-8")) <= 230 and ch == 2   # LoRa BYTES, channel kept

    def test_truncation_counts_bytes_not_chars(self):
        # 'п' is 2 UTF-8 bytes: 150 chars = 300 bytes would overflow the radio's
        # 237-byte payload and raise inside sendText (refute 2026-07-21)
        b = MeshBridge()

        class FakeIface:
            def __init__(self):
                self.sent = []

            def sendText(self, text, channelIndex=0):
                assert len(text.encode("utf-8")) <= 237, "payload overflow"
                self.sent.append(text)
        b._iface = FakeIface()
        assert b.send("п" * 150) is True
        assert len(b._iface.sent[0].encode("utf-8")) <= 230

    def test_receive_closure_is_strongly_referenced(self):
        # pypubsub holds listeners by WEAK ref: a bare local closure is GC'd and
        # the receive half silently never fires (refute 2026-07-21). The bridge
        # must pin the closure on the instance.
        import gc
        b = MeshBridge()

        class FakePub:
            def __init__(self):
                self.subscribed = []

            def subscribe(self, fn, topic):
                import weakref
                self.subscribed.append((weakref.ref(fn), topic))

        import sys
        fake = type(sys)("pubsub")
        fake.pub = FakePub()
        sys.modules["pubsub"] = fake
        try:
            b._subscribe()
        finally:
            del sys.modules["pubsub"]
        gc.collect()
        assert b._on_receive_fn is not None
        ref, topic = fake.pub.subscribed[0]
        assert ref() is b._on_receive_fn             # weakref still alive
        assert topic == "meshtastic.receive.text"

    def test_listener_registry_ignores_non_callables(self):
        b = MeshBridge()
        b.on_text(None)                              # type: ignore[arg-type]
        b.on_text(lambda s, t: None)
        assert len(b._listeners) == 1


class TestExtism:
    def test_run_none_without_wheel(self):
        h = ExtismHost()
        if not ExtismHost.available:
            assert h.ready is False
            assert h.run(b"\x00asm", "run") is None
            assert default_extism_host() is None

    def test_input_guards_refuse_junk(self):
        h = ExtismHost()
        assert h.run(b"", "run") is None             # empty module
        assert h.run("notbytes", "run") is None      # type: ignore[arg-type]
        assert h.run(b"\x00asm" * (9 * 1024 * 1024), "run") is None   # >32MB
        assert h.run(b"\x00asm", "") is None         # no function name

    def test_limits_are_clamped(self):
        h = ExtismHost(timeout_ms=999_999, max_pages=999_999)
        assert h.timeout_ms == 30_000 and h.max_pages == 1024
        low = ExtismHost(timeout_ms=1, max_pages=1)
        assert low.timeout_ms == 100 and low.max_pages == 16


class TestImmich:
    PEOPLE = json.dumps({"people": [
        {"name": "Sam", "assetCount": 42},
        {"name": "", "assetCount": 9},               # unnamed cluster → skipped
        {"name": "Priya", "faceCount": 7},
    ]}).encode()

    def test_public_base_is_refused_structurally(self):
        s = ImmichSource("https://photos.example.com", "key")
        assert s.available is False and s.people() == []
        assert default_immich("https://photos.example.com") is None

    def test_lan_base_parses_people(self):
        s = ImmichSource("http://192.168.1.10:2283", "key",
                         fetch_fn=lambda url, headers, timeout=4.0: self.PEOPLE)
        people = s.people()
        assert [p["name"] for p in people] == ["Sam", "Priya"]   # named only, by faces

    def test_api_key_rides_the_header(self):
        seen = {}

        def fetch(url, headers, timeout=4.0):
            seen.update(headers)
            return self.PEOPLE
        ImmichSource("http://192.168.1.10:2283", "sekrit", fetch_fn=fetch).people()
        assert seen.get("x-api-key") == "sekrit"

    def test_junk_replies_degrade(self):
        s = ImmichSource("http://192.168.1.10:2283",
                         fetch_fn=lambda url, headers, timeout=4.0: b"{nope")
        assert s.people() == [] and s.memories() == []


class TestHomeAssistant:
    STATES = [
        {"entity_id": "cover.garage_door", "state": "open",
         "attributes": {"friendly_name": "Garage door", "device_class": "garage_door"}},
        {"entity_id": "binary_sensor.smoke_kitchen", "state": "on",
         "attributes": {"friendly_name": "Kitchen smoke", "device_class": "smoke"}},
        {"entity_id": "lock.front", "state": "unlocked",
         "attributes": {"friendly_name": "Front door lock"}},
        {"entity_id": "light.hall", "state": "on",
         "attributes": {"friendly_name": "Hall light"}},          # boring → silent
        {"entity_id": "cover.blinds", "state": "closed",
         "attributes": {"friendly_name": "Blinds"}},
        {"entity_id": "cover.living_room_blinds", "state": "open",
         "attributes": {"friendly_name": "Living room blinds",
                        "device_class": "blind"}},                 # open all day → silent
        {"entity_id": "cover.shade_kitchen", "state": "open",
         "attributes": {"friendly_name": "Kitchen shade"}},        # bare cover → silent
        "garbage",                                                 # skipped
    ]

    def test_alert_policy_is_narrow_and_ranked(self):
        alerts = home_alerts(self.STATES)
        assert [a.level for a in alerts] == ["watchout", "listen", "listen"]
        assert "Smoke alarm at home" in alerts[0].clue
        clues = " | ".join(a.clue for a in alerts)
        assert "Garage door is still open" in clues
        assert "Front door lock is unlocked" in clues
        assert "Hall light" not in clues              # a HUD, not a nag
        # a cover only alerts when it's an OPENING (door/garage/gate/window) —
        # blinds and shades open all day (refute 2026-07-21)
        assert "blinds" not in clues.lower() and "shade" not in clues.lower()

    def test_policy_never_raises_on_junk(self):
        assert home_alerts(None) == []
        assert home_alerts([{}, {"entity_id": 5}]) == []

    def test_public_base_refused_and_states_seam(self):
        assert HomeBridge("https://ha.example.com", "t").available is False
        assert default_home_bridge("https://ha.example.com") is None
        b = HomeBridge("http://192.168.1.5:8123", "tok",
                       fetch_fn=lambda url, headers, timeout=4.0:
                       json.dumps(self.STATES[:1]).encode())
        assert len(b.alerts()) == 1

    def test_bearer_token_rides_the_header(self):
        seen = {}

        def fetch(url, headers, timeout=4.0):
            seen.update(headers)
            return b"[]"
        HomeBridge("http://192.168.1.5:8123", "tok", fetch_fn=fetch).states()
        assert seen.get("Authorization") == "Bearer tok"


class TestDawarich:
    POINTS = json.dumps([
        {"timestamp": 1_752_900_000, "latitude": 37.77, "longitude": -122.42},
        {"timestamp": "2026-07-20T11:00:00Z", "latitude": 37.78, "longitude": -122.41},
        {"latitude": "bad"},                          # skipped
    ]).encode()

    def test_public_base_refused(self):
        assert DawarichSource("https://timeline.example.com").available is False
        assert default_dawarich("https://timeline.example.com") is None

    def test_points_parse_both_timestamp_eras(self):
        s = DawarichSource("http://192.168.1.7:3000", "k",
                           fetch_fn=lambda url, headers, timeout=4.0: self.POINTS)
        pts = s.points()
        assert len(pts) == 2 and pts[0]["ts"] > pts[1]["ts"]      # newest first

    def test_at_finds_the_nearest_point_within_tolerance(self):
        s = DawarichSource("http://192.168.1.7:3000", "k",
                           fetch_fn=lambda url, headers, timeout=4.0: self.POINTS)
        hit = s.at(1_752_900_100)
        assert hit is not None and hit["lat"] == 37.77
        assert s.at(1_700_000_000) is None            # too far from any point
        assert s.at("junk") is None                   # type: ignore[arg-type]


def test_wave_n4_capabilities_registered():
    from dreamlayer import capabilities as C
    caps = {c.key: c for c in C.CAPABILITIES}
    assert caps["mesh_range"].extra == "mesh" and "meshtastic" in caps["mesh_range"].modules
    assert caps["extism_plugins"].extra == "extism" and "extism" in caps["extism_plugins"].modules
    for key in ("immich_people", "home_hud", "location_spine", "folder_sync"):
        assert caps[key].kind == "service", key


def test_syncthing_probe_and_recipe_exist():
    from dreamlayer import capabilities as C
    assert C.has_probe_url("folder_sync")
    assert "8384" in C._PROBE_URLS["folder_sync"]
    # configured-base services must NOT have a static probe (they'd be branded
    # unreachable while live on a base we don't know — refute 2026-07-21)
    for key in ("immich_people", "home_hud", "location_spine"):
        assert not C.has_probe_url(key)
    from pathlib import Path
    recipe = Path(__file__).resolve().parents[4] / "docs" / "SYNCTHING.md"
    assert recipe.is_file() and "peer-to-peer" in recipe.read_text()
