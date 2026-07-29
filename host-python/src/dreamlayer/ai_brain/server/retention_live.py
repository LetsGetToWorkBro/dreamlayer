"""retention_live.py — the memory lifecycle, wired into the shipped Brain.

The lifecycle (`memory/retention.py`) was written years ago and never ran. The
diagnosis is `decisions/0001`: `RetentionSweep` is constructed in exactly one
place, `Orchestrator.maybe_dream_tonight`, that method has no production caller,
and it returns early anyway — and none of that is the real problem. The real
problem is that **the shipped Brain never builds an `Orchestrator` at all**, so
everything hanging off it is invisible from the user's seat.

So this does what `ear.py` and `glance_live.py` did before it: run the proven
primitive against the Brain's OWN store, without dragging in an Orchestrator
(which would bring a second `MemoryDB` and a heavy reasoning graph beside the
one the Brain already has). `RetentionSweep` itself is not Orchestrator-owned —
it is a plain pass over a `MemoryDB` — so it is reused here rather than
reimplemented; only the wiring is new.

The tiers, unchanged from the design the docs describe:

  hot   (`retention_hot_hours`, 24 h)  the live sighting ring the world lens
                                       keeps in memory — dropped past its window.
  warm  (`retention_warm_days`, 90 d)  `memories` rows on disk — deleted, with
                                       their ANN vectors, past their window.
  cold  (forever)                      entities: people, promises, tasks,
                                       teaches, places. Only an explicit
                                       "forget that" removes them.

Both windows come from `dreamlayer.config.CONFIG`, which already declares and
clamps them. The conservatism is the primitive's and is deliberately kept:
**an unknown age keeps the row**, **`meta.pinned` never expires**, and cold
kinds are never even considered.

Two differences from the Orchestrator's nightly pass, both because the Brain
has no REM:

  * `bias=None`. The REM `RetrievalBias` is a dreamer's vote to keep a memory
    past its window; the Brain runs no nightly REM, so no such votes exist and
    there is no vault to persist a discard to. The other three conservatisms
    still hold, so this narrows nothing except the "kept by REM" escape hatch,
    which cannot be populated here.
  * no alternate vector store. Nothing in the Brain wires a Chroma/Lance
    `VectorStore` (only the Orchestrator's `Retriever` can hold one), so there
    is no second index to go purge-blind on. The ANN sidecar, which the Brain
    DOES use, is wired below.

Never raises into boot: a Brain whose memory file is missing, locked, or
corrupt must still start.
"""
from __future__ import annotations

import logging
import os
import time

log = logging.getLogger("dreamlayer.retention.brain")

# How often a running Brain turns the lifecycle over. Boot is the other trigger;
# on a machine that stays awake for weeks, boot alone would mean "nothing ages
# out" all over again — the exact shape of the bug this module exists to fix.
SWEEP_INTERVAL_S = 3600.0


def brain_retention_policy():
    """The lifecycle windows, read from `config.py` at call time.

    Read live rather than captured at import: `CONFIG` is a mutable runtime
    singleton (`config.Config.__post_init__` clamps negatives away), so a
    caller that adjusts a window gets it honoured on the next sweep.
    """
    from ...config import CONFIG
    from ...memory.retention import RetentionPolicy
    return RetentionPolicy(
        hot_hours=float(getattr(CONFIG, "retention_hot_hours", 24.0)),
        warm_days=float(getattr(CONFIG, "retention_warm_days", 90.0)),
    )


def _ann_for(db, db_path: str):
    """The Brain's ANN sidecar for this database, or None.

    A warm row deleted while its vector survives is a memory you can still find
    by similarity — so the sweep must reach the index too. Wired exactly the way
    the erase path (`server._erase_memories`) and the Ember burn wire it: the
    embedding dimension is read off the db's own settings, and a missing
    `usearch` (the `memory` extra) simply means no index to evict from.
    """
    try:
        from ...memory.ann_index import PersistentAnnIndex
        if not PersistentAnnIndex.available:
            return None
        dim = db.get_setting("embedder_dim")
        if not dim:
            return None
        return PersistentAnnIndex(db_path + ".usearch", int(dim))
    except Exception as exc:                     # noqa: BLE001 — index is optional
        log.warning("[retention] ANN index unavailable: %s", exc)
        return None


def _hot_ring(brain):
    """The Brain's live hot ring, if one is already built — never build one.

    `WorldLensHost` owns the same `SemanticRingBuffer` the glasses run, and it
    is where a look's sighting memory lives ("seen before 3× · last at …").
    It is deliberately read off the CACHED attribute rather than through
    `brain.world_lens()`: that accessor CONSTRUCTS the host (vision router,
    lens registry, installed plugins), which is far too much to do for a sweep,
    and at boot there is nothing in the ring to purge anyway — it is in-memory,
    so a restart already emptied it. The hot window bites on the periodic
    sweep of a Brain that has been up long enough to have looked at something.
    """
    wl = getattr(brain, "_world_lens", None)
    return getattr(wl, "ring", None) if wl is not None else None


def _sweep_warm(brain, policy) -> dict:
    """The warm tier: `memories` rows on disk past `retention_warm_days`, with
    their ANN vectors. Returns the fields of the report it owns."""
    db_path = _memory_db_path(brain)
    if not db_path or not os.path.exists(db_path):
        return {"ok": True, "reason": "no-memory-db"}   # nothing stored yet
    try:
        from ...memory.db import MemoryDB
        from ...memory.retention import RetentionSweep
        db = MemoryDB(db_path)
    except Exception as exc:                     # noqa: BLE001 — never fail boot
        log.warning("[retention] memory store unreadable: %s", exc)
        return {"ok": False, "reason": "db-unreadable"}
    try:
        result = RetentionSweep(db, policy, ann=_ann_for(db, db_path)).sweep()
        return {"ok": True, "swept": result.swept,
                "expired": len(result.expired),
                "kept_cold": result.kept_cold,
                "kept_pinned": result.kept_pinned}
    except Exception as exc:                     # noqa: BLE001
        log.warning("[retention] warm sweep failed: %s", exc)
        return {"ok": False, "reason": "sweep-failed"}
    finally:
        try:
            db.conn.close()                      # a boot sweep must not hold the file
        except Exception:                        # noqa: BLE001
            pass


def sweep_retention(brain) -> dict:
    """Age the Brain's memory out by policy. Returns a small report dict.

    Best-effort by construction — every failure mode degrades to "kept", which
    is the right direction for a retention pass: keeping a row too long is a
    disclosed limitation, deleting one we should not have is unrecoverable.
    """
    report = {"ok": False, "swept": 0, "expired": 0, "kept_cold": 0,
              "kept_pinned": 0, "hot_purged": 0}
    policy = brain_retention_policy()
    # The two tiers are swept independently, and the warm one is NOT allowed to
    # return early past the hot one: the hot ring lives in memory and has no
    # relationship to the database file, so "no memory file yet" (a fresh
    # install that has only ever looked at things) must still age sightings out.
    report.update(_sweep_warm(brain, policy))
    # The statement ring (lens_hosts) is a hot store too, and it must age out on
    # the SAME window rather than inventing its own — a second hot store with its
    # own policy is how "nothing expires" comes back.
    ls = getattr(brain, "_lenses", None)
    if ls is not None:
        try:
            cutoff = time.time() - policy.hot_hours * 3600.0
            report["hot_purged"] += int(ls.purge_hot(cutoff))
        except Exception as exc:                     # noqa: BLE001
            log.warning("[retention] statement-ring purge failed: %s", exc)
    # Auto-enrolled faces nobody named age out on the WARM window. A named
    # contact is a deliberate keep and stays cold-forever; an unnamed one is a
    # stranger the camera happened to see, and keeping those permanently grows
    # the store without bound with people the wearer could not identify.
    fr = getattr(brain, "_face_recall", None)
    if fr is not None:
        try:
            report["unnamed_faces_dropped"] = int(
                fr.sweep_unnamed(policy.warm_days))
        except Exception as exc:                     # noqa: BLE001
            log.warning("[retention] unnamed-face sweep failed: %s", exc)
    ring = _hot_ring(brain)
    if ring is not None:
        try:
            cutoff = time.time() - policy.hot_hours * 3600.0
            report["hot_purged"] = int(ring.purge_before(cutoff))
        except Exception as exc:                 # noqa: BLE001
            log.warning("[retention] hot purge failed: %s", exc)
    if report["expired"] or report["hot_purged"]:
        # The ledger is the privacy promise: an automatic deletion the wearer
        # did not ask for is exactly the kind of thing that must be visible in
        # it. Counts only — never what was forgotten.
        try:
            brain.activity.add(
                "retention",
                f"Retention swept memory ({report['expired']} row(s) past "
                f"{policy.warm_days:g}d, {report['hot_purged']} sighting(s) past "
                f"{policy.hot_hours:g}h)")
        except Exception:                        # noqa: BLE001
            pass
    return report


def _memory_db_path(brain) -> str:
    """Where the Brain's memory SQLite lives — deliberately delegated to
    `server._memory_db_path` rather than re-derived, so the sweep can never end
    up pointed at a different file than the erase, Ember and `dreamlayer
    memories` paths ($DREAMLAYER_DB, else <cfg_dir>/dreamlayer.db). Imported at
    call time: `server` imports this module the same way, so neither is a
    circular import at load."""
    try:
        from .server import _memory_db_path as _resolve
        return str(_resolve(brain))
    except Exception as exc:                     # noqa: BLE001
        log.warning("[retention] memory path unresolvable: %s", exc)
        return ""
