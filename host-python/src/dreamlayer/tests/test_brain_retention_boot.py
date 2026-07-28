"""test_brain_retention_boot.py — the memory lifecycle, proved by deletion.

`decisions/0001`: nothing on the device ever expired. `RetentionSweep` existed,
was unit-tested, and had no live caller — it hung off an `Orchestrator` the
shipped Brain never builds. The fix wires the same primitive into the Brain
(`ai_brain/server/retention_live.py`), beside the boot prune that already ages
out the ask history and activity log.

Every assertion here is about a ROW THAT IS GONE, from a real `Brain(cfg_dir)`
boot against a real SQLite file on disk. That is deliberate: the finding this
closes is a feature that passed its tests without ever deleting anything, so a
test that only checks a report object, a call count, or a policy field would
reproduce the original failure exactly. If the boot hook is removed, every
`assert ... not in surviving` below fails.

The conservatism is pinned just as hard as the deletion, because over-deleting
is the unrecoverable direction: cold entities, pinned rows, and rows of unknown
age all survive a sweep that removes the row next to them.
"""
from __future__ import annotations

import time

import pytest

from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server.store import BrainConfig
from dreamlayer.memory.db import MemoryDB

DAY = 86400.0


@pytest.fixture(autouse=True)
def _no_db_override(monkeypatch):
    """`_memory_db_path` honours $DREAMLAYER_DB first; a developer with it set
    would otherwise point these at their own memory file — and this suite
    DELETES rows. Pin it to the per-test cfg dir by clearing the override."""
    monkeypatch.delenv("DREAMLAYER_DB", raising=False)


def _seed(db_path, rows):
    """Write rows with a chosen age. `created_at` is stamped by the store, so
    the age is applied afterwards with a direct UPDATE — the row is genuinely
    old rather than the clock being genuinely wrong, which is what the sweep
    will see in production."""
    db = MemoryDB(str(db_path))
    ids = {}
    for name, kind, age_days, meta in rows:
        mid = db.add_memory(kind, f"summary for {name}", meta=meta)
        stamp = ("" if age_days is None else
                 _iso(time.time() - age_days * DAY))
        db.conn.execute("UPDATE memories SET created_at=? WHERE id=?",
                        (stamp, mid))
        ids[name] = mid
    db.conn.commit()
    db.conn.close()
    return ids


def _iso(ts: float) -> str:
    from datetime import datetime, UTC
    return datetime.fromtimestamp(ts, UTC).isoformat()


def _surviving(db_path) -> set[int]:
    db = MemoryDB(str(db_path))
    try:
        return {m["id"] for m in db.memories()}
    finally:
        db.conn.close()


def _brain(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    BrainConfig(token="tok").save(cfg)
    return cfg


class TestRowsActuallyDisappearOnBoot:
    """The claim decision 0001 says was false: memory ages out on its own."""

    def test_a_row_past_the_warm_window_is_gone_after_boot(self, tmp_path):
        cfg = _brain(tmp_path)
        db_path = cfg / "dreamlayer.db"
        ids = _seed(db_path, [
            # (name, kind, age in days, meta)
            ("expired", "conversation", 200, None),
            ("fresh",   "conversation", 1,   None),
        ])

        assert _surviving(db_path) == set(ids.values()), "seed did not land"

        Brain(cfg)                                   # the boot hook, nothing else

        survivors = _surviving(db_path)
        assert ids["expired"] not in survivors, (
            "a 200-day-old warm memory survived a Brain boot — the retention "
            "lifecycle is not running, which is decision 0001 all over again")
        assert ids["fresh"] in survivors, (
            "boot deleted a memory from yesterday — the warm window is not "
            "being honoured")

    def test_the_default_window_is_the_one_config_declares(self, tmp_path):
        """91 days out dies, 89 lives — the boundary is `retention_warm_days`
        (90.0), not some number this module invented."""
        from dreamlayer.config import CONFIG
        assert CONFIG.retention_warm_days == 90.0, "config default moved"

        cfg = _brain(tmp_path)
        db_path = cfg / "dreamlayer.db"
        ids = _seed(db_path, [("just_past", "object", 91, None),
                              ("just_inside", "object", 89, None)])

        Brain(cfg)

        survivors = _surviving(db_path)
        assert ids["just_past"] not in survivors
        assert ids["just_inside"] in survivors

    def test_a_commitment_extracted_from_an_expired_memory_goes_with_it(
            self, tmp_path):
        """`purge_memory` cascades to commitments sourced from the row. An
        expired memory that leaves "wire Ana the deposit" standing in the
        reminders surface has not been forgotten."""
        cfg = _brain(tmp_path)
        db_path = cfg / "dreamlayer.db"
        db = MemoryDB(str(db_path))
        mid = db.add_memory("conversation", "an old promise was made")
        db.conn.execute("UPDATE memories SET created_at=? WHERE id=?",
                        (_iso(time.time() - 400 * DAY), mid))
        db.add_commitment("Ana", "wire the deposit", source_memory_id=mid)
        db.conn.commit()
        db.conn.close()

        Brain(cfg)

        db = MemoryDB(str(db_path))
        try:
            assert db.memories() == []
            assert db.commitments() == [], (
                "the expired memory's commitment outlived the memory itself")
        finally:
            db.conn.close()


class TestTheConservatismSurvivesTheWiring:
    """Over-deleting is the unrecoverable direction. Each of these rows is
    older than the warm window and must still be there afterwards."""

    def test_cold_entities_are_forever(self, tmp_path):
        cfg = _brain(tmp_path)
        db_path = cfg / "dreamlayer.db"
        cold = [("person", "person"), ("promise", "promise"), ("task", "task"),
                ("taught", "taught"), ("place", "place")]
        ids = _seed(db_path, [(k, k, 900, None) for _, k in cold]
                    + [("warm", "conversation", 900, None)])

        Brain(cfg)

        survivors = _surviving(db_path)
        for _, kind in cold:
            assert ids[kind] in survivors, (
                f"a {kind} entity was swept — cold kinds are forever, only an "
                f"explicit forget removes them")
        assert ids["warm"] not in survivors, (
            "nothing was deleted at all, so 'cold survives' proves nothing")

    def test_a_pinned_row_never_expires(self, tmp_path):
        cfg = _brain(tmp_path)
        db_path = cfg / "dreamlayer.db"
        ids = _seed(db_path, [("pinned", "conversation", 900, {"pinned": True}),
                              ("unpinned", "conversation", 900, None)])

        Brain(cfg)

        survivors = _surviving(db_path)
        assert ids["pinned"] in survivors, "a pinned memory expired"
        assert ids["unpinned"] not in survivors

    def test_unknown_age_means_keep(self, tmp_path):
        """A row whose `created_at` cannot be read is kept. When in doubt the
        sweep keeps — the alternative is deleting a memory because a timestamp
        was malformed."""
        cfg = _brain(tmp_path)
        db_path = cfg / "dreamlayer.db"
        ids = _seed(db_path, [("blank", "conversation", None, None),
                              ("dated", "conversation", 900, None)])
        db = MemoryDB(str(db_path))
        garbled = db.add_memory("conversation", "a garbled stamp")
        db.conn.execute("UPDATE memories SET created_at=? WHERE id=?",
                        ("not-a-timestamp", garbled))
        db.conn.commit()
        db.conn.close()

        Brain(cfg)

        survivors = _surviving(db_path)
        assert ids["blank"] in survivors, "an undated row was deleted"
        assert garbled in survivors, "a row with an unparseable stamp was deleted"
        assert ids["dated"] not in survivors


class TestTheHotWindow:
    """`retention_hot_hours` over the live sighting ring — the Brain's hot
    store. In-memory, so boot always finds it empty; it bites on the periodic
    sweep of a Brain that has been up long enough to have looked at things."""

    def test_sightings_past_the_hot_window_are_dropped(self, tmp_path):
        from dreamlayer.pipelines.ingest import MemoryEvent

        cfg = _brain(tmp_path)
        brain = Brain(cfg)
        ring = brain.world_lens().ring          # the REAL host's ring
        now = time.time()
        ring.append(MemoryEvent(kind="object", summary="a mug, yesterday"),
                    ts=now - 30 * 3600)         # past the 24 h window
        ring.append(MemoryEvent(kind="object", summary="a mug, just now"),
                    ts=now - 60)
        assert len(ring) == 2

        report = brain.sweep_retention()

        assert report["hot_purged"] == 1
        assert len(ring) == 1, "the stale sighting is still in the hot ring"
        assert ring.latest()[0].event.summary == "a mug, just now"

    def test_the_hot_ring_is_swept_even_with_no_memory_file(self, tmp_path):
        """The two tiers are independent. A fresh install that has only ever
        LOOKED at things has no `dreamlayer.db` at all — and the first draft of
        this module returned early on that, so sightings never aged out."""
        from dreamlayer.pipelines.ingest import MemoryEvent

        cfg = _brain(tmp_path)
        brain = Brain(cfg)
        assert not (cfg / "dreamlayer.db").exists()
        brain.world_lens().ring.append(
            MemoryEvent(kind="object", summary="a mug, days ago"),
            ts=time.time() - 30 * 3600)

        assert brain.sweep_retention()["hot_purged"] == 1
        assert len(brain.world_lens().ring) == 0

    def test_boot_does_not_build_a_world_lens_just_to_sweep(self, tmp_path):
        """Constructing `WorldLensHost` pulls in the vision router, the lens
        registry and every installed plugin. A retention sweep must not be the
        thing that does it — the ring is empty at boot regardless."""
        cfg = _brain(tmp_path)
        brain = Brain(cfg)
        assert getattr(brain, "_world_lens", None) is None


class TestTheSweepIsSafeAndRepeatable:
    def test_no_memory_file_is_not_an_error(self, tmp_path):
        cfg = _brain(tmp_path)
        assert not (cfg / "dreamlayer.db").exists()
        report = Brain(cfg).sweep_retention()
        assert report["ok"] is True
        assert report["expired"] == 0

    def test_an_unreadable_store_does_not_stop_the_brain_booting(self, tmp_path):
        cfg = _brain(tmp_path)
        (cfg / "dreamlayer.db").write_bytes(b"this is not a database")
        brain = Brain(cfg)                      # must not raise
        assert brain.sweep_retention()["ok"] is False

    def test_the_sweep_is_recorded_in_the_activity_ledger(self, tmp_path):
        """An automatic deletion the wearer did not ask for has to be visible
        in the ledger that is the privacy promise. Counts only."""
        cfg = _brain(tmp_path)
        _seed(cfg / "dreamlayer.db", [("old", "conversation", 400, None)])
        brain = Brain(cfg)
        kinds = [r["kind"] for r in brain.activity.recent(50)]
        assert "retention" in kinds, "memory was swept and the ledger is silent"

    def test_the_scheduler_keeps_sweeping_after_boot(self, tmp_path):
        """Boot alone would mean a Brain that stays up for a month never ages
        anything out again."""
        cfg = _brain(tmp_path)
        db_path = cfg / "dreamlayer.db"
        brain = Brain(cfg)
        ids = _seed(db_path, [("late", "conversation", 400, None)])
        brain.start_retention_scheduler(interval=0.02)
        try:
            deadline = time.time() + 10.0
            while time.time() < deadline and ids["late"] in _surviving(db_path):
                time.sleep(0.05)
            assert ids["late"] not in _surviving(db_path), (
                "the scheduled sweep never ran")
        finally:
            brain.stop_retention_scheduler()

    def test_starting_the_scheduler_twice_is_a_no_op(self, tmp_path):
        brain = Brain(_brain(tmp_path))
        brain.start_retention_scheduler(interval=30.0)
        first = brain._retention_stop
        brain.start_retention_scheduler(interval=30.0)
        assert brain._retention_stop is first
        brain.stop_retention_scheduler()
        assert brain._retention_stop is None


class TestTheWiringItself:
    def test_the_orchestrator_is_still_not_resurrected(self):
        """The obvious fix — give `maybe_dream_tonight` a caller — is the wrong
        one: it would stand a second `MemoryDB` and a reasoning graph up beside
        the Brain's own, which is what `ear.py:4-10` records the team choosing
        twice not to do. This pins that the fix went the other way."""
        import re
        from pathlib import Path
        src = Path(__file__).resolve().parents[1]
        callers = []
        for path in src.rglob("*.py"):
            if "tests" in path.parts or path.name == "ops_dream_rem.py":
                continue
            if re.search(r"\.maybe_dream_tonight\s*\(", path.read_text()):
                callers.append(str(path.relative_to(src)))
        assert not callers, f"the Orchestrator sweep was resurrected in {callers}"

    def test_the_policy_comes_from_config_not_a_literal(self, monkeypatch):
        from dreamlayer.ai_brain.server import retention_live
        from dreamlayer.config import CONFIG

        monkeypatch.setattr(CONFIG, "retention_warm_days", 7.0)
        monkeypatch.setattr(CONFIG, "retention_hot_hours", 2.0)
        policy = retention_live.brain_retention_policy()
        assert (policy.warm_days, policy.hot_hours) == (7.0, 2.0)

    def test_a_shortened_window_is_honoured_end_to_end(self, tmp_path,
                                                       monkeypatch):
        """Not just read into a dataclass — a row that is inside the default
        window and outside a shortened one is deleted when the window moves."""
        from dreamlayer.config import CONFIG
        cfg = _brain(tmp_path)
        db_path = cfg / "dreamlayer.db"
        ids = _seed(db_path, [("ten_days", "conversation", 10, None)])

        Brain(cfg)
        assert ids["ten_days"] in _surviving(db_path), "10 days is inside 90"

        monkeypatch.setattr(CONFIG, "retention_warm_days", 7.0)
        Brain(cfg)
        assert ids["ten_days"] not in _surviving(db_path), (
            "the shortened warm window was not honoured")
