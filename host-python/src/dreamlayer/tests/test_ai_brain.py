"""test_ai_brain.py — Phase 1: the tiered brain, mocks, and the AI Object Lens."""
from __future__ import annotations

import numpy as np

from dreamlayer.ai_brain import (
    BrainRouter, MockVisionBrain, MockKnowledgeBrain, Answer,
)
from dreamlayer.object_lens import (
    ObjectLens, ObjectRecognizer, ProviderRegistry, AIProvider,
)

DEVICE_FACTS = {"snake plant": "a snake plant", "mug": "a mug"}
LAPTOP_FACTS = {"snake plant": "snake plant — water every 2-3 weeks, low light",
                "rioja": "2018 Rioja, pairs with lamb, drink now"}
CLOUD_FACTS = {"trilobite fossil": "an Ordovician trilobite, ~450M years old"}


def frame():
    a = np.full((16, 16), 0.6, dtype=np.float32)
    a[::2] += 0.15
    return a


def full_router(cloud_opt_in=False):
    r = BrainRouter(cloud_opt_in=cloud_opt_in)
    r.add_vision(MockVisionBrain("device", DEVICE_FACTS, serves_deep=False))
    r.add_vision(MockVisionBrain("laptop", LAPTOP_FACTS, serves_deep=True))
    r.add_vision(MockVisionBrain("cloud", CLOUD_FACTS, is_cloud=True))
    return r


class TestRouterVision:
    def test_lowest_tier_answers_quick(self):
        ans = full_router().explain(frame(), "snake plant")
        assert ans.tier == "device" and ans.text == "a snake plant"

    def test_more_escalates_past_the_small_tier(self):
        ans = full_router().explain(frame(), "snake plant", want="more")
        assert ans.tier == "laptop" and "2-3 weeks" in ans.text

    def test_only_laptop_knows_it(self):
        ans = full_router().explain(frame(), "rioja")
        assert ans.tier == "laptop"

    def test_cloud_is_gated_off_by_default(self):
        assert full_router().explain(frame(), "trilobite fossil") is None

    def test_cloud_answers_once_opted_in(self):
        r = full_router()
        r.opt_in_cloud(True)
        ans = r.explain(frame(), "trilobite fossil")
        assert ans.tier == "cloud" and "trilobite" in ans.text

    def test_unknown_object_no_answer(self):
        assert full_router().explain(frame(), "flux capacitor") is None

    def test_a_dead_tier_is_skipped_not_fatal(self):
        class Broken:
            tier, is_cloud = "device", False
            def explain(self, *a, **k): raise RuntimeError("model crashed")
        r = BrainRouter()
        r.add_vision(Broken())
        r.add_vision(MockVisionBrain("laptop", LAPTOP_FACTS))
        assert r.explain(frame(), "rioja").tier == "laptop"


class TestRouterKnowledge:
    def _router(self):
        r = BrainRouter()
        r.add_knowledge(MockKnowledgeBrain({
            "lease.pdf": "Rent is 2400 per month due on the first.\n"
                         "The lease ends in June.",
            "notes.md": "Marcus prefers email over calls."}))
        return r

    def test_answers_from_your_own_docs_with_source(self):
        ans = self._router().ask("how much is the rent")
        assert "2400" in ans.text and ans.sources == ["lease.pdf"]
        assert ans.tier == "laptop"

    def test_no_match_returns_none(self):
        assert self._router().ask("what is the airspeed of a swallow") is None


class TestAIObjectLens:
    def test_provider_inert_without_a_tier(self):
        # empty router -> AIProvider contributes nothing, panel still builds
        lens = ObjectLens(
            recognizer=ObjectRecognizer(classify_fn=lambda _f: ("mug", 0.9, {})),
            registry=ProviderRegistry([AIProvider(BrainRouter())]))
        panel = lens.look(frame())
        assert panel is not None and panel.is_empty()

    def test_look_at_anything_gets_an_explanation(self):
        lens = ObjectLens(
            recognizer=ObjectRecognizer(
                classify_fn=lambda _f: ("snake plant", 0.9, {})),
            registry=ProviderRegistry([AIProvider(full_router())]))
        panel = lens.look(frame())
        assert any(r.label == "about" and "snake plant" in r.detail
                   for r in panel.rows)
        assert any("ai (device)" in r.source for r in panel.rows)

    def test_answer_cached_per_label(self):
        calls = {"n": 0}
        class Counting:
            tier, is_cloud = "device", False
            def explain(self, frame, label, want="quick"):
                calls["n"] += 1
                return Answer(text=f"a {label}", tier="device")
        r = BrainRouter(); r.add_vision(Counting())
        prov = AIProvider(r)
        from dreamlayer.object_lens import ObjectSighting
        prov.build(ObjectSighting("mug", 0.9))
        prov.build(ObjectSighting("mug", 0.9))
        assert calls["n"] == 1                 # explained once, cached


class TestOrchestratorWiring:
    def _orc(self):
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        return Orchestrator(FakeBridge())

    def test_brain_ships_inert_and_lights_up(self):
        orc = self._orc()
        orc.object_lens.recognizer = ObjectRecognizer(
            classify_fn=lambda _f: ("snake plant", 0.9, {}))
        # inert: no vision tier yet -> only the memory provider (no "about")
        panel = orc.look_at_object(frame())
        assert not any(r.label == "about" for r in panel.rows)
        # enable the Mac mini brain -> the same glance now explains
        orc.brain.add_vision(MockVisionBrain("laptop", LAPTOP_FACTS))
        for p in orc.object_lens.registry._providers:      # clear the AI cache
            if isinstance(p, AIProvider):
                p._cache.clear()
        panel = orc.look_at_object(frame())
        assert any(r.label == "about" for r in panel.rows)

    def test_ask_brain_and_cloud_gate(self):
        orc = self._orc()
        orc.brain.add_knowledge(MockKnowledgeBrain(
            {"lease.pdf": "Rent is 2400 per month."}))
        ans = orc.ask_brain("what's the rent")
        assert ans is not None and "2400" in ans.text
        assert any(f.get("t") == "card" for f in orc.bridge.raw)
        # cloud is opt-in (product posture); private mode still forces it off
        assert orc.brain.cloud_opt_in is False
        orc.opt_in_cloud(True)
        assert orc.brain.cloud_opt_in is True
        orc.set_private_mode(True)
        assert orc.brain.cloud_opt_in is False and orc.private_mode is True
        orc.set_private_mode(False)
        assert orc.brain.cloud_opt_in is True

    def test_ask_brain_is_veil_gated(self):
        orc = self._orc()
        orc.brain.add_knowledge(MockKnowledgeBrain({"x": "secret 42"}))
        orc.privacy.pause()
        assert orc.ask_brain("secret") is None
