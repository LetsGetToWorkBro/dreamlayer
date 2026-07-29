"""Rewind your day — `TimeScrubNodeCard`, and the claim that was wrong about it.

This card was recorded as blocked on "a durable store the Brain lacks". That
was a mis-read: the hot ring already IS the day. It carries a timestamp and a
kind per entry and is swept on `retention_hot_hours`, so the scrub timeline is
"everything since the cutoff, newest first" and needs nothing new on disk.

What the tests pin is the part that is easy to get wrong once it is wired: the
card's meaning is POSITIONAL. `index` and `total` place the progress dot, so a
producer that fills only {primary, footer} draws a scrubber that never moves —
the same mistake `_drift_card` made and HANDOFF records.
"""
from __future__ import annotations

import tempfile
import time

import pytest

from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.pipelines.ingest import MemoryEvent


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _pushes(brain):
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card)) or 1)
    return seen


def _fill(ls, n, *, age_step=60.0):
    now = time.time()
    for i in range(n):
        ls.ring.append(MemoryEvent(kind="object", summary=f"moment {i}",
                                   confidence=0.8),
                       ts=now - i * age_step)


def test_an_empty_day_draws_nothing(brain):
    """`total: 0` is the honest answer. Drawing node 1 of 0 would be a card
    describing a moment that does not exist."""
    ls = brain.lenses()
    seen = _pushes(brain)
    out = ls.scrub(0)
    assert out["total"] == 0 and out["pushed"] == 0
    assert seen == []


def test_the_ring_is_the_timeline(brain):
    ls = brain.lenses()
    _fill(ls, 5)
    out = ls.scrub(0, push=False)
    assert out["total"] == 5
    assert [n["summary"] for n in out["nodes"]] == [f"moment {i}" for i in range(5)]


def test_the_card_carries_its_position(brain):
    """The whole point of the card. Without index/total the drawing has no
    scrubber and every node looks identical."""
    ls = brain.lenses()
    _fill(ls, 4)
    seen = _pushes(brain)
    ls.scrub(2)
    kind, card = seen[-1]
    assert kind == "time_scrub"
    assert card["type"] == "TimeScrubNodeCard"
    assert card["index"] == 2 and card["total"] == 4
    assert card["summary"] == "moment 2"
    assert card["ts_label"]


def test_a_stale_index_is_clamped_not_rejected(brain):
    """A phone holding a position from before a retention sweep must get the
    oldest node, not a 400 and not a wrap round to the newest."""
    ls = brain.lenses()
    _fill(ls, 3)
    out = ls.scrub(99)
    assert out["index"] == 2
    out = ls.scrub(-5)
    assert out["index"] == 0


def test_the_veil_answers_nothing(brain):
    """Scrubbing the day is recall, and recall is veiled. Distinct from an
    empty day only in that the ring is untouched."""
    ls = brain.lenses()
    _fill(ls, 3)
    brain.config.network_mode = "lan_only"
    seen = _pushes(brain)
    out = ls.scrub(0)
    assert out["total"] == 0 and seen == []


def test_only_the_hot_window_counts(brain):
    """A node older than the retention window is not part of "your day"."""
    ls = brain.lenses()
    now = time.time()
    ls.ring.append(MemoryEvent(kind="object", summary="today"), ts=now - 60)
    ls.ring.append(MemoryEvent(kind="object", summary="last week"),
                   ts=now - 8 * 86400)
    out = ls.scrub(0, push=False)
    assert [n["summary"] for n in out["nodes"]] == ["today"]


def test_the_route_reaches_it(brain):
    """A lens method nothing routes to is the exact failure this whole audit is
    about. Asserted against the real dispatch table, not a direct call."""
    from dreamlayer.ai_brain.server import server as srv
    src = (srv.__file__ or "")
    assert src
    text = open(src, encoding="utf-8").read()
    assert '"/dreamlayer/scrub": _get_scrub,' in text
    assert "def _get_scrub(self, path, qs):" in text
