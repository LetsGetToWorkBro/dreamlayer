"""test_cloud_view.py — the "what the cloud can see" payload (B16, Cat 6): the
server reports only opaque byte-shapes, and names what it can never see."""
from __future__ import annotations

from dreamlayer.ai_brain.server.server import _cloud_view_payload


class _FakeBrain:
    def __init__(self, caps=()):
        self._caps = frozenset(caps)

    def plugin_capabilities(self):
        return self._caps


def test_reports_only_opaque_shapes_and_the_guarantees():
    p = _cloud_view_payload(_FakeBrain())
    assert p["enabled"] is False
    assert p["vault"] is None
    assert p["relay"]["rooms"] == [] and p["listings"] == 0
    assert any("memories" in c for c in p["cannot_see"])
    assert any("who you are" in c for c in p["cannot_see"])


def test_enabled_when_a_cloud_capability_is_present():
    assert _cloud_view_payload(_FakeBrain({"cloud_sync"}))["enabled"] is True
    assert _cloud_view_payload(_FakeBrain({"midi"}))["enabled"] is False
