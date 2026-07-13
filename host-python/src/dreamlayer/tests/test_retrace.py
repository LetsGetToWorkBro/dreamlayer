"""test_retrace.py — Retrace (INNOVATION_SESSION 2.6): "where are my keys?" →
the last place the ambient pipeline *understood* them, with the time. Recall from
40-byte rows, no image stored; recency-blended; veil-gated."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dreamlayer.main import build
from dreamlayer.orchestrator.ops_commitments import CommitmentRecallOps


def _sighting(orch, obj, place, created_at=None):
    mid = orch.db.add_memory(kind="object", summary=obj, confidence=0.8,
                             meta={"object": obj, "place": place})
    if created_at:
        orch.db.conn.execute("UPDATE memories SET created_at=? WHERE id=?",
                             (created_at, mid))
        orch.db.conn.commit()
    return mid


def test_retrace_answers_place_and_time():
    orch = build(":memory:")
    _sighting(orch, "keys", "kitchen counter")
    r = orch.retrace("keys")
    assert r["found"] and r["place"] == "kitchen counter"
    assert "kitchen counter" in r["say"] and r["when"]
    assert orch.bridge.last_card["type"] == "ObjectRecallCard"


def test_retrace_prefers_the_most_recent_sighting():
    orch = build(":memory:")
    _sighting(orch, "keys", "hallway table", "2026-07-08T19:00:00")
    _sighting(orch, "keys", "kitchen counter", "2026-07-10T08:40:00")
    r = orch.retrace("keys")
    assert r["found"] and r["place"] == "kitchen counter"   # the last understood


def test_retrace_not_found_when_never_seen():
    orch = build(":memory:")
    r = orch.retrace("unicorn")
    assert r["found"] is False


def test_retrace_is_recall_gated():
    # retrace is a *read* of past sightings: the full pause veil holds it (and
    # the copy says so — not the old "incognito" line, which was wrong since it
    # only ever triggered on pause), but incognito allows recall.
    orch = build(":memory:")
    _sighting(orch, "keys", "kitchen counter")
    orch.privacy.pause()
    r = orch.retrace("keys")
    assert r["found"] is False and "veil" in r["say"].lower()
    assert "incognito" not in r["say"].lower()
    orch.privacy.resume()
    orch.set_incognito(True)
    assert orch.retrace("keys")["found"] is True      # incognito allows recall


def test_locate_falls_back_to_retrace_without_an_anchor():
    orch = build(":memory:")
    _sighting(orch, "keys", "kitchen counter")
    r = orch._locate("keys")               # no Waypath anchor dropped
    assert r["found"] and r["place"] == "kitchen counter"


def test_human_when_phrases():
    now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    f = CommitmentRecallOps._human_when
    today = now.replace(hour=8, minute=40)
    assert f(today.isoformat(), now=now) == "8:40am"
    assert f((today - timedelta(days=1)).isoformat(), now=now) == "8:40am yesterday"
    older = f((today - timedelta(days=5)).isoformat(), now=now)
    assert older.startswith("8:40am on ")
