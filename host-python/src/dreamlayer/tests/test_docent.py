"""test_docent.py — Docent Lens (INNOVATION_SESSION 4.5): a venue publishes a
place-keyed knowledge layer; look at the exhibit, hear the curator. Grounded in
the venue's own LocalRecall collection, offline, veil-gated."""
from __future__ import annotations

from dreamlayer.main import build
from dreamlayer.memory.localrecall_api import LocalRecallClient


def _venue():
    """An in-memory venue collection (no server) — offline, like a synced ticket."""
    c = LocalRecallClient(base_url=None, collection="museum")
    c.add("The blue vase is Ming dynasty, circa 1500, cobalt underglaze.",
          metadata={"exhibit": "vase"})
    c.add("The tapestry depicts the harvest festival of the northern valley.",
          metadata={"exhibit": "tapestry"})
    return c


def test_docent_answers_from_the_venue_collection():
    orch = build(":memory:")
    card = orch.docent("blue vase ming", client=_venue())
    assert card["type"] == "ScholarCard"
    assert "ming" in card["primary"].lower() or "vase" in card["primary"].lower()


def test_docent_uses_a_synthesizer_when_given():
    orch = build(":memory:")
    card = orch.docent("vase", client=_venue(),
                       synth=lambda q, passages: "A Ming vase, about 1500.")
    assert card["primary"] == "A Ming vase, about 1500."


def test_docent_none_without_a_venue_client():
    orch = build(":memory:")
    assert orch.docent("anything") is None


def test_docent_none_when_nothing_matches():
    orch = build(":memory:")
    assert orch.docent("spaceship laser", client=_venue()) is None


def test_docent_is_veil_gated():
    orch = build(":memory:")
    orch.privacy.pause()
    assert orch.docent("vase", client=_venue()) is None
