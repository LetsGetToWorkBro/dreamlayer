"""test_brain_tiers.py — Bring-Your-Own-Brain ceremony (INNOVATION_SESSION 3.1).

The host half: the health ledger now records per-tier latency, and the Brain
exposes the tier ladder (on-device → Mac mini → cloud) with that latency + the
switch state, so the phone can render the router's judgment and swap it.
"""
from __future__ import annotations

from dreamlayer.orchestrator.health import HealthLedger
from dreamlayer.ai_brain.server.server import _brain_view_payload, Brain


class TestLedgerLatency:
    def test_record_ok_tracks_latency(self):
        h = HealthLedger()
        h.record_ok("brain:cloud", ms=100.0)
        h.record_ok("brain:cloud", ms=200.0)
        snap = h.snapshot()["brain:cloud"]
        assert snap["successes"] == 2
        assert 100.0 <= snap["latency_ms"] <= 200.0        # smoothed between them

    def test_latency_is_optional_and_back_compatible(self):
        h = HealthLedger()
        h.record_ok("brain:device")                        # no ms — old callers
        assert "latency_ms" not in h.snapshot()["brain:device"]


class TestBrainView:
    def test_ladder_shape_and_switches(self, tmp_path):
        brain = Brain(tmp_path)
        view = _brain_view_payload(brain)
        ids = [t["id"] for t in view["tiers"]]
        assert ids == ["device", "mac_mini", "cloud"]      # preference order
        assert "model" in view and "active_tier" in view
        assert view["tiers"][0]["enabled"] is True          # on-device always on

    def test_latency_surfaces_per_tier(self, tmp_path):
        brain = Brain(tmp_path)
        brain.health.record_ok("brain:mac_mini", ms=42.0)
        view = _brain_view_payload(brain)
        mac = next(t for t in view["tiers"] if t["id"] == "mac_mini")
        assert mac["latency_ms"] == 42.0 and mac["seen"] is True
        # a tier that never answered has no latency and isn't marked seen
        cloud = next(t for t in view["tiers"] if t["id"] == "cloud")
        assert cloud["latency_ms"] is None and cloud["seen"] is False

    def test_active_tier_is_the_highest_preference_enabled(self, tmp_path):
        brain = Brain(tmp_path)
        # on-device is always allowed and highest preference, so it answers first
        assert _brain_view_payload(brain)["active_tier"] == "device"
        # incognito drops cloud out of the enabled set
        brain.config.network_mode = "lan_only"
        view = _brain_view_payload(brain)
        assert view["incognito"] is True
        assert next(t for t in view["tiers"] if t["id"] == "cloud")["enabled"] is False
