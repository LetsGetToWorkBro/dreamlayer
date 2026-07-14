"""test_ember_endpoint.py — the phone Ember screen's real backend.

GET  /dreamlayer/ember       the practice: status, offers, curves — no answers
POST /dreamlayer/ember/tend  the morning choice (keeps capped per day)
POST /dreamlayer/ember/burn  the ceremony (consent only, tombstone planted)
"""
from __future__ import annotations

import os

from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server.server import (
    _ember_burn, _ember_state, _ember_store_path, _ember_tend,
    _memory_db_path,
)
from dreamlayer.ember import EmberStore, RecallOutcome, next_review
from dreamlayer.ember.engram import TendingCandidate
from dreamlayer.memory.db import MemoryDB

NOW = 1_700_000_000.0
ANSWER = "Maya said her first full sentence in Spanish"


def brain_with_store(tmp_path):
    os.environ["DREAMLAYER_DB"] = str(tmp_path / "dreamlayer.db")
    try:
        b = Brain(tmp_path)
        store = EmberStore(_ember_store_path(b))
        return b, store
    finally:
        del os.environ["DREAMLAYER_DB"]


def test_state_is_clean_before_any_tending(tmp_path):
    b = Brain(tmp_path)
    s = _ember_state(b)
    assert s["ok"] and s["exists"] is False
    assert s["candidates"] == [] and s["engrams"] == []


def test_state_ships_cues_and_curves_never_answers(tmp_path):
    import time
    b, store = brain_with_store(tmp_path)
    store.keep("k1", "What did Maya say?", ANSWER, time.time() - 86400)
    s = _ember_state(b)
    assert s["exists"] and s["status"]["tended"] == 1
    assert s["engrams"][0]["cue"] == "What did Maya say?"
    assert ANSWER not in str(s), \
        "the answer must never leave the hub — the glass reveal is the only surface"


def test_tend_keep_and_let_go_and_the_daily_cap(tmp_path):
    import time
    from dreamlayer.ember.tending import MAX_KEEPS_PER_DAY
    b, store = brain_with_store(tmp_path)
    cands = [TendingCandidate(id=0, kind="memory", summary=f"a fine moment {i}",
                              cue=f"cue {i}", salience=1.0 - i * 0.01)
             for i in range(MAX_KEEPS_PER_DAY + 2)]
    store.add_candidates(cands, time.time())
    staged = store.candidates()

    assert _ember_tend(b, {"candidate_id": staged[0].id, "keep": False})["ok"]
    kept = [_ember_tend(b, {"candidate_id": c.id, "keep": True})
            for c in staged[1:]]
    assert sum(1 for r in kept if r["ok"]) == MAX_KEEPS_PER_DAY
    assert any("ritual" in (r.get("error") or "") for r in kept if not r["ok"])


def test_erase_all_memories_erases_the_practice_too(tmp_path):
    """The phone's 'Erase all memories' must not leave engram answers behind:
    rows purged, offers purged, and the answer text gone from the file's raw
    bytes (purge_all VACUUMs — DELETE alone leaves scrubbed-out pages)."""
    import time
    b, store = brain_with_store(tmp_path)
    store.keep("k1", "What did Maya say?", ANSWER, time.time())
    store.add_candidates([TendingCandidate(
        id=0, kind="memory", summary="a secret picnic at the reservoir",
        cue="About secret picnic… — what happened?", salience=1.0)],
        time.time())

    r = b.purge_memories()
    assert r["ok"] and r["embers_purged"] == 1

    path = _ember_store_path(b)
    fresh = EmberStore(path)
    assert fresh.engrams(include_burned=True) == []
    assert fresh.candidates() == []
    import pathlib
    raw = pathlib.Path(path).read_bytes()
    assert b"Spanish" not in raw and b"reservoir" not in raw
    # a brain with no ember store yet purges cleanly too
    b2 = Brain(tmp_path / "other")
    assert b2.purge_memories()["embers_purged"] == 0


def test_burn_needs_consent_and_actually_burns(tmp_path):
    import time
    b, store = brain_with_store(tmp_path)
    now = time.time()

    os.environ["DREAMLAYER_DB"] = str(tmp_path / "dreamlayer.db")
    try:
        db = MemoryDB(str(_memory_db_path(b)))
        mid = db.add_memory("conversation", ANSWER, confidence=0.9)
        e = store.keep("k1", "What did Maya say?", ANSWER, now,
                       source_memory_id=mid)
        st = e.state
        while not st.graduated:
            st = next_review(st, RecallOutcome.EASY, st.due_ts)
        store._write_state(e.id, st)

        no = _ember_burn(b, {"engram_id": e.id})
        assert no["ok"] is False and "consent" in no["error"]
        no2 = _ember_burn(b, {"engram_id": e.id, "consent": "yes"})
        assert no2["ok"] is False, "consent must be boolean true, not truthy"

        r = _ember_burn(b, {"engram_id": e.id, "consent": True})
        assert r["ok"] and r["purged_memory_id"] == mid
        # the recording is gone; the cue-only tombstone is pinned
        db2 = MemoryDB(str(_memory_db_path(b)))
        assert db2.memory(mid) is None
        tomb = db2.memory(r["tombstone_memory_id"])
        assert tomb["kind"] == "ember" and ANSWER not in str(tomb)
        assert EmberStore(_ember_store_path(b)).get(e.id).burned
    finally:
        del os.environ["DREAMLAYER_DB"]
