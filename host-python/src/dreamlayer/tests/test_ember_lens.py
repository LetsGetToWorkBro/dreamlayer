"""test_ember_lens.py — Ember Lens (INNOVATION_SESSION 4.9): a gentle anniversary
layer. Only memories you chose to keep (pinned), a year ago today, ever surface —
one line, never an ambush, storm-suppressed, veil-gated."""
from __future__ import annotations

import datetime as dt

from dreamlayer.main import build

NOW = dt.datetime(2026, 7, 10, tzinfo=dt.timezone.utc)


def _memory_a_year_ago(orch, summary, pinned, offset_days=0):
    when = (NOW - dt.timedelta(days=365) + dt.timedelta(days=offset_days)).isoformat()
    mid = orch.db.add_memory(kind="taught", summary=summary,
                             meta={"pinned": pinned})
    orch.db.conn.execute("UPDATE memories SET created_at=? WHERE id=?", (when, mid))
    orch.db.conn.commit()
    return mid


def test_ember_surfaces_a_pinned_year_old_memory():
    orch = build(":memory:")
    _memory_a_year_ago(orch, "the thing Dad said about bread", pinned=True)
    card = orch.ember(now=NOW)
    assert card is not None and "bread" in str(card).lower()


def test_ember_ignores_unpinned_memories():
    orch = build(":memory:")
    _memory_a_year_ago(orch, "a passing sighting", pinned=False)
    assert orch.ember(now=NOW) is None


def test_ember_is_suppressed_by_a_storm():
    orch = build(":memory:")
    _memory_a_year_ago(orch, "kept moment", pinned=True)
    assert orch.ember(now=NOW, weather="storm") is None


def test_ember_is_veil_gated():
    orch = build(":memory:")
    _memory_a_year_ago(orch, "kept moment", pinned=True)
    orch.privacy.pause()
    assert orch.ember(now=NOW) is None


def test_ember_none_when_nothing_from_a_year_ago():
    orch = build(":memory:")
    # pinned, but recent (created now) → not an anniversary
    orch.db.add_memory(kind="taught", summary="today", meta={"pinned": True})
    assert orch.ember(now=NOW) is None
