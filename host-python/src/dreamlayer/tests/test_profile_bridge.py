"""test_profile_bridge.py — the hub->Brain bridge for the Oracle profile.

The Oracle profile is built on the glasses hub (from the conversation stream),
then *pushed* to the Brain so the phone can read it. The Brain only mirrors what
the hub sends; it never authors the profile.
"""
from __future__ import annotations

from dreamlayer.ai_brain.server import Brain
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


# -- Brain stores and persists the mirror -------------------------------------

def test_brain_stores_and_persists_profile(tmp_path):
    cfg = tmp_path / "cfg"; cfg.mkdir()
    brain = Brain(cfg)
    assert brain.profile == {}
    out = brain.set_profile({"name": "Sam", "interests": ["astronomy", "sailing"],
                             "people": ["Marcus"], "preferences": ["I prefer aisle seats"],
                             "observations": 42})
    assert out["name"] == "Sam" and "astronomy" in out["interests"]
    fresh = Brain(cfg)                       # a restart reads the same file
    assert fresh.profile["name"] == "Sam"
    assert fresh.profile["observations"] == 42


def test_set_profile_keeps_only_the_known_shape(tmp_path):
    cfg = tmp_path / "cfg"; cfg.mkdir()
    brain = Brain(cfg)
    out = brain.set_profile({"name": "Sam", "secret": "leak", "interests": "notalist"})
    assert "secret" not in out
    assert out["interests"] == []            # a bad type becomes empty, not a crash


# -- the hub pushes its snapshot ----------------------------------------------

def test_publish_profile_posts_the_snapshot():
    orc = Orchestrator(FakeBridge())
    orc.brain_url = "http://mac.local:7777"
    orc.user.learn("Call me Sam")
    orc.ingest_caption("I love astronomy and telescopes.", speaker="", ts=1.0)
    sent = {}

    def fake_post(url, body, token=""):
        sent["url"] = url; sent["body"] = body
        return {"ok": True}

    out = orc.publish_profile(http_post=fake_post)
    assert out == {"ok": True}
    assert sent["url"].endswith("/dreamlayer/profile")
    assert sent["body"]["name"] == "Sam"
    assert "astronomy" in sent["body"]["interests"]


def test_publish_is_silent_without_a_mac_mini():
    orc = Orchestrator(FakeBridge())         # no brain_url set
    assert orc.publish_profile(http_post=lambda *a, **k: {"ok": True}) is None


def test_a_teach_pushes_immediately():
    orc = Orchestrator(FakeBridge())
    orc.brain_url = "http://mac.local:7777"
    posts = []
    orc.publish_profile = lambda http_post=None: posts.append(1)  # type: ignore
    orc.ask_oracle("Remember that I prefer window seats")
    assert posts, "an explicit teach should push the profile right away"
