"""ember/store.py — the archive that empties itself into you.

Ember gets its own SQLite file (default beside the memory DB) rather than a
table in memory/schema.sql, for one load-bearing reason: engrams must survive
`purge_all` semantics differently from memories. A full memory wipe erases
what the glasses know; an engram is a record of what *you* know — its whole
point is to outlive the recording. Separate file, separate lifecycle, and
`RetentionSweep` can never touch it by construction.

Thread discipline is MemoryDB's exactly: one cross-thread connection, every
statement behind one RLock (capture-side keeps run off the ingest thread
while prompts read on the tick/place thread).

Two tables:
  engrams — kept moments and their scheduler state (see engram.py)
  tending — the night's candidates awaiting the wearer's morning choice
"""
from __future__ import annotations

import json
import sqlite3
import threading

from .engram import Engram, TendingCandidate
from .scheduler import EngramState, RecallOutcome, next_review, seed_state

_SCHEMA = """
CREATE TABLE IF NOT EXISTS engrams (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    moment_key       TEXT NOT NULL UNIQUE,
    cue              TEXT NOT NULL,
    answer           TEXT NOT NULL DEFAULT '',
    kept_at          REAL NOT NULL,
    place_signature  TEXT NOT NULL DEFAULT '',
    source_memory_id INTEGER NOT NULL DEFAULT 0,
    burned           INTEGER NOT NULL DEFAULT 0,
    burned_at        REAL NOT NULL DEFAULT 0,
    meta             TEXT,
    stability        REAL NOT NULL,
    difficulty       REAL NOT NULL,
    due_ts           REAL NOT NULL,
    reps             INTEGER NOT NULL DEFAULT 0,
    lapses           INTEGER NOT NULL DEFAULT 0,
    last_review_ts   REAL NOT NULL DEFAULT 0,
    graduated        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tending (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    night_seed       INTEGER NOT NULL DEFAULT 0,
    kind             TEXT NOT NULL DEFAULT 'memory',
    summary          TEXT NOT NULL,
    cue              TEXT NOT NULL,
    salience         REAL NOT NULL DEFAULT 0,
    place_signature  TEXT NOT NULL DEFAULT '',
    source_memory_id INTEGER NOT NULL DEFAULT 0,
    created_ts       REAL NOT NULL DEFAULT 0,
    resolved         TEXT NOT NULL DEFAULT ''
);
"""


class EmberStore:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    # -- keeping -----------------------------------------------------------

    def keep(self, moment_key: str, cue: str, answer: str, now: float, *,
             place_signature: str = "", source_memory_id: int = 0,
             first_impression: RecallOutcome = RecallOutcome.GOOD,
             meta: dict | None = None) -> Engram:
        """The tending choice: a moment becomes an engram. Idempotent on
        moment_key — keeping the same moment twice returns the existing
        engram untouched (a double-tap must not reset a curve).

        The existence check and the INSERT run under ONE lock acquisition
        (audit 2026-07-14): two concurrent double-taps used to both see no row
        and both INSERT, and the UNIQUE(moment_key) constraint then raised an
        uncaught IntegrityError instead of honoring idempotency. Now the loser
        of the race falls back to the row the winner wrote."""
        state = seed_state(now, first_impression)
        with self._lock:
            existing = self.by_key(moment_key)
            if existing is not None:
                return existing
            try:
                c = self.conn.execute(
                    "INSERT INTO engrams(moment_key,cue,answer,kept_at,"
                    "place_signature,source_memory_id,meta,stability,difficulty,"
                    "due_ts,reps,lapses,last_review_ts,graduated) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (moment_key, cue, answer, now, place_signature,
                     source_memory_id, json.dumps(meta or {}), state.stability,
                     state.difficulty, state.due_ts, state.reps, state.lapses,
                     state.last_review_ts, int(state.graduated)))
                self.conn.commit()
                assert c.lastrowid is not None
                return self.get(c.lastrowid)  # type: ignore[return-value]
            except sqlite3.IntegrityError:
                return self.by_key(moment_key)  # type: ignore[return-value]

    # -- reading -----------------------------------------------------------

    def get(self, engram_id: int) -> Engram | None:
        with self._lock:
            r = self.conn.execute("SELECT * FROM engrams WHERE id=?",
                                  (engram_id,)).fetchone()
        return Engram.from_row(dict(r)) if r else None

    def by_key(self, moment_key: str) -> Engram | None:
        with self._lock:
            r = self.conn.execute("SELECT * FROM engrams WHERE moment_key=?",
                                  (moment_key,)).fetchone()
        return Engram.from_row(dict(r)) if r else None

    def engrams(self, include_burned: bool = False) -> list[Engram]:
        q = "SELECT * FROM engrams" + \
            ("" if include_burned else " WHERE burned=0") + " ORDER BY kept_at"
        with self._lock:
            rows = self.conn.execute(q).fetchall()
        return [Engram.from_row(dict(r)) for r in rows]

    def due(self, now: float, place_signature: str | None = None,
            limit: int = 1) -> list[Engram]:
        """Engrams whose prompt may fire, most overdue first. Place-gating is
        the method of loci made literal: an engram anchored to a place fires
        only when the wearer stands in it; an unanchored engram fires
        anywhere. Burned engrams never fire — the practice ended when the
        wearer chose to end it."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM engrams WHERE burned=0 AND due_ts<=? "
                "ORDER BY due_ts", (now,)).fetchall()
        out = []
        for r in rows:
            sig = r["place_signature"] or ""
            if sig and sig != (place_signature or ""):
                continue
            out.append(Engram.from_row(dict(r)))
            if len(out) >= limit:
                break
        return out

    def graduated_unburned(self) -> list[Engram]:
        """The standing offers: memories that now live in the wearer, whose
        recordings still exist. The ceremony reads this; nothing burns
        without explicit consent (ceremony.burn)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM engrams WHERE graduated=1 AND burned=0 "
                "ORDER BY kept_at").fetchall()
        return [Engram.from_row(dict(r)) for r in rows]

    # -- reviewing ---------------------------------------------------------

    def record_review(self, engram_id: int, outcome: RecallOutcome,
                      now: float) -> Engram | None:
        """One recall attempt, through the scheduler, persisted."""
        e = self.get(engram_id)
        if e is None or e.burned:
            return None
        state = next_review(e.state, outcome, now)
        self._write_state(engram_id, state)
        return e.with_state(state)

    def _write_state(self, engram_id: int, s: EngramState) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE engrams SET stability=?,difficulty=?,due_ts=?,reps=?,"
                "lapses=?,last_review_ts=?,graduated=? WHERE id=?",
                (s.stability, s.difficulty, s.due_ts, s.reps, s.lapses,
                 s.last_review_ts, int(s.graduated), engram_id))
            self.conn.commit()

    # -- burning -----------------------------------------------------------

    def mark_burned(self, engram_id: int, now: float) -> Engram | None:
        """Record that the raw trace is gone. The answer column is blanked in
        the same statement — after a burn the store holds only the cue and
        the curve, exactly what the tombstone claims. Purging the *source*
        memory row (and its ANN vector) is the ceremony's job; this method
        only makes the engram side truthful."""
        with self._lock:
            self.conn.execute(
                "UPDATE engrams SET burned=1, burned_at=?, answer='' "
                "WHERE id=?", (now, engram_id))
            self.conn.commit()
        return self.get(engram_id)

    def purge_all(self) -> None:
        """Erase the whole practice: every engram (answers included) and
        every staged offer. This is the wearer's erase-everything, which is
        a different thing from the retention lifecycle (which never touches
        this file — see the module docstring): surviving an automatic sweep
        is the design; surviving the owner's explicit wipe would be a
        privacy residue. VACUUM afterwards, because a bare DELETE only
        frees SQLite pages without scrubbing them — "erased" must mean the
        answer text is no longer in the file's bytes."""
        with self._lock:
            self.conn.execute("DELETE FROM engrams")
            self.conn.execute("DELETE FROM tending")
            self.conn.commit()
            self.conn.execute("VACUUM")

    # -- tending candidates --------------------------------------------------

    def add_candidates(self, candidates: list[TendingCandidate],
                       now: float) -> int:
        """Stage the night's offers. Any still-unresolved offer from an
        earlier night is released first (an offer is for one morning; stale
        candidates piling up would turn a ritual into an inbox)."""
        with self._lock:
            self.conn.execute(
                "UPDATE tending SET resolved='let_go' WHERE resolved=''")
            for c in candidates:
                self.conn.execute(
                    "INSERT INTO tending(night_seed,kind,summary,cue,salience,"
                    "place_signature,source_memory_id,created_ts) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (c.night_seed, c.kind, c.summary, c.cue, c.salience,
                     c.place_signature, c.source_memory_id, now))
            self.conn.commit()
        return len(candidates)

    def candidates(self) -> list[TendingCandidate]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM tending WHERE resolved='' "
                "ORDER BY salience DESC").fetchall()
        return [TendingCandidate(
            id=r["id"], kind=r["kind"], summary=r["summary"], cue=r["cue"],
            salience=r["salience"], place_signature=r["place_signature"],
            source_memory_id=r["source_memory_id"], night_seed=r["night_seed"],
        ) for r in rows]

    def resolve_candidate(self, candidate_id: int, kept: bool) -> TendingCandidate | None:
        with self._lock:
            r = self.conn.execute("SELECT * FROM tending WHERE id=? AND resolved=''",
                                  (candidate_id,)).fetchone()
            if r is None:
                return None
            self.conn.execute("UPDATE tending SET resolved=? WHERE id=?",
                              ("kept" if kept else "let_go", candidate_id))
            self.conn.commit()
        return TendingCandidate(
            id=r["id"], kind=r["kind"], summary=r["summary"], cue=r["cue"],
            salience=r["salience"], place_signature=r["place_signature"],
            source_memory_id=r["source_memory_id"], night_seed=r["night_seed"])

    # -- readout -------------------------------------------------------------

    def status(self, now: float) -> dict:
        engrams = self.engrams(include_burned=True)
        live = [e for e in engrams if not e.burned]
        return {
            "tended": len(live),
            # everything past due, including place-anchored engrams waiting
            # for the wearer to stand in the right doorway
            "due": sum(1 for e in live if e.state.due_ts <= now),
            "graduated": sum(1 for e in live if e.state.graduated),
            "burned": sum(1 for e in engrams if e.burned),
            "candidates": len(self.candidates()),
        }
