"""test_facets_and_posture.py — Juno facets (own/ai/shop) + network posture."""
from __future__ import annotations

import numpy as np

from dreamlayer.object_lens import (
    ObjectLens, ObjectRecognizer, ProviderRegistry,
    LabelProvider, ShoppingProvider, DietaryProfile, AIProvider,
)
from dreamlayer.ai_brain import BrainRouter, MockVisionBrain
from dreamlayer.ai_brain.server import BrainConfig


def frame():
    a = np.full((16, 16), 0.6, dtype=np.float32)
    a[::2] += 0.15
    return a


def says(label, **attrs):
    return ObjectRecognizer(classify_fn=lambda _f: (label, 0.9, attrs))


def _lens():
    router = BrainRouter()
    router.add_vision(MockVisionBrain("laptop", {"kettle": "a 1.7L kettle"}))
    return ObjectLens(
        recognizer=says("kettle"),
        registry=ProviderRegistry([
            LabelProvider(DietaryProfile()),                      # facet own
            AIProvider(router),                                   # facet ai
            ShoppingProvider(lambda l, a: {"cheaper": "$18 nearby"}),  # facet shop
        ]))


class TestFacets:
    def test_own_glance_stays_private(self):
        lens = _lens()
        panel = lens.look(frame(), facets={"own"})
        assert all(r.source not in ("ai", "shopping") for r in panel.rows)
        assert not any(r.label == "about" for r in panel.rows)   # no AI
        assert not any(r.label == "cheaper nearby" for r in panel.rows)  # no shop

    def test_ai_facet_explains(self):
        panel = _lens().look(frame(), facets={"ai"})
        assert any(r.label == "about" for r in panel.rows)
        assert not any(r.label == "cheaper nearby" for r in panel.rows)

    def test_shop_facet_prices(self):
        panel = _lens().look(frame(), facets={"shop"})
        assert any(r.label == "cheaper nearby" for r in panel.rows)
        assert not any(r.label == "about" for r in panel.rows)

    def test_no_facet_shows_everything(self):
        panel = _lens().look(frame())              # default: all facets
        labels = {r.label for r in panel.rows}
        assert "about" in labels and "cheaper nearby" in labels

    def test_orchestrator_facet_param(self):
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        orc = Orchestrator(FakeBridge())
        orc.object_lens.recognizer = says("cheese", ingredients="milk")
        orc.dietary.avoid.add("dairy")
        # a private glance: your own facts only
        panel = orc.look_at_object(frame(), facet="own")
        assert any(r.detail == "dairy" for r in panel.rows)


class TestNetworkPosture:
    def test_config_default_is_connected_but_cloud_is_opt_in(self):
        c = BrainConfig()
        assert c.network_mode == "connected" and c.cloud_enabled is False
        assert c.lan_only is False

    def test_lan_only_is_the_advanced_opt_out(self):
        c = BrainConfig(network_mode="lan_only")
        assert c.lan_only is True

    def test_orchestrator_cloud_off_until_opted_in(self):
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        orc = Orchestrator(FakeBridge())
        assert orc.brain.cloud_opt_in is False and orc.private_mode is False
        orc.opt_in_cloud(True)
        assert orc.brain.cloud_opt_in is True
        orc.set_private_mode(True)                 # incognito forces cloud off…
        assert orc.brain.cloud_opt_in is False
        orc.set_private_mode(False)                # …and restores the opt-in after
        assert orc.brain.cloud_opt_in is True
