from __future__ import annotations
import sqlite3, os, json, threading
from datetime import datetime, UTC

class MemoryDB:
    """The memory store.

    Capture runs on a daemon thread (orchestrator/capture.py: mic -> VAD ->
    ASR -> ingest_caption), while recall and the panel read on other threads,
    so a single SQLite connection is shared across threads. sqlite3 forbids
    that by default (check_same_thread) and isn't safe for concurrent access
    anyway, so the connection is opened cross-thread and every statement is
    serialized behind one reentrant lock. Without this a spoken commitment
    captured off-thread raised deep in add_commitment and was silently lost.
    """
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # Whether a DELETE scrubs the freed page or leaves the plaintext in the
        # file is a COMPILE-TIME default (SECURE_DELETE), and it differs between
        # the Debian build and the python.org macOS build the "full Brain" runs
        # on. Set it explicitly so a deletion means the same thing everywhere.
        try:
            self.conn.execute("PRAGMA secure_delete=ON")
        except sqlite3.Error:                     # ancient build: VACUUM still covers purge_all
            pass
        self._lock = threading.RLock()
        schema = os.path.join(os.path.dirname(__file__), "schema.sql")
        with self._lock:
            self.conn.executescript(open(schema).read())
            self.conn.commit()
    def _now(self): return datetime.now(UTC).isoformat()

    def _scrub(self, text):
        """PII-scrub one piece of caller text before it becomes a column.

        This is what delivers the Guardian pack's "PII scrubbed before write"
        promise, and it has to be applied at EVERY write of caller text, not just
        `add_memory`. `add_memory`'s comment used to call itself "the single write
        chokepoint every capture path funnels through" -- but `IngestPipeline
        .ingest` calls `add_commitment` three lines earlier with the same
        transcript, so a card number spoken inside a promise landed verbatim in
        `commitments.task` and was served to the phone by the reminders surface.

        `default_redactor()` returns None when the pii_redaction cap is toggled
        off (DL_DISABLE_PII_REDACTION, the panel switch), so this is on by default
        and still switch-off-able. It strips only verbatim contact/financial
        identifiers (card, SSN, phone, email) -- never names or places -- so
        name-recall, the product's whole point, is untouched."""
        if not isinstance(text, str) or not text:
            return text
        from .pii_presidio import default_redactor
        red = default_redactor()
        if red is None:
            return text
        try:
            return red.redact(text)
        except Exception:                         # never let redaction break a write
            return text

    def add_memory(self, kind, summary, embedding=None, confidence=0.5, place_id=None, meta=None) -> int:
        summary = self._scrub(summary)
        # embeddings persist as packed float32 BLOBs (embeddings.pack_embedding);
        # readers accept legacy JSON-text rows too, so no migration pass is needed
        from .embeddings import pack_embedding
        with self._lock:
            c = self.conn.execute("INSERT INTO memories(kind,summary,embedding,confidence,place_id,created_at,meta) VALUES (?,?,?,?,?,?,?)",
                (kind, summary, pack_embedding(embedding) if embedding else None, confidence, place_id, self._now(), json.dumps(meta or {})))
            self.conn.commit(); assert c.lastrowid is not None; return c.lastrowid
    def memory(self, memory_id: int):
        with self._lock:
            r = self.conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return dict(r) if r else None
    def update_embedding(self, memory_id: int, embedding) -> None:
        # a lock-guarded backfill: capture runs off-thread, so a bare
        # self.conn.execute(...) from an ops mixin raced the writer lock and
        # could interleave commits (the exact hazard the class lock exists for).
        from .embeddings import pack_embedding
        with self._lock:
            self.conn.execute("UPDATE memories SET embedding=? WHERE id=?",
                              (pack_embedding(embedding) if embedding else None, memory_id))
            self.conn.commit()
    def update_meta(self, memory_id: int, meta) -> None:
        with self._lock:
            self.conn.execute("UPDATE memories SET meta=? WHERE id=?",
                              (json.dumps(meta or {}), memory_id))
            self.conn.commit()
    def get_setting(self, key: str, default=None):
        with self._lock:
            r = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default
    def set_setting(self, key: str, value: str):
        with self._lock:
            self.conn.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            self.conn.commit()
    def add_commitment(self, person, task, due=None, source_memory_id=None, confidence=0.5) -> int:
        task = self._scrub(task)                  # same chokepoint as add_memory
        with self._lock:
            c = self.conn.execute("INSERT INTO commitments(person,task,due,source_memory_id,confidence,created_at) VALUES (?,?,?,?,?,?)",
                (person, task, due, source_memory_id, confidence, self._now()))
            self.conn.commit(); assert c.lastrowid is not None; return c.lastrowid
    def add_place(self, name, signature=None) -> int:
        with self._lock:
            c = self.conn.execute("INSERT INTO places(name,signature) VALUES (?,?)", (name, signature))
            self.conn.commit(); assert c.lastrowid is not None; return c.lastrowid
    def memories(self, kind=None):
        q = "SELECT * FROM memories" + (" WHERE kind=?" if kind else "")
        with self._lock:
            return [dict(r) for r in self.conn.execute(q, (kind,) if kind else ()).fetchall()]
    def commitments(self, person=None):
        q = "SELECT * FROM commitments" + (" WHERE person=?" if person else "")
        with self._lock:
            return [dict(r) for r in self.conn.execute(q, (person,) if person else ()).fetchall()]
    def places(self):
        with self._lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM places").fetchall()]
    def purge_memory(self, memory_id: int):
        with self._lock:
            self.conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            # A commitment extracted FROM this memory is part of it. "Forget that"
            # deleted the memory and left "wire Ana the deposit" standing in
            # `commitments`, where the reminders surface still reads it.
            self.conn.execute("DELETE FROM commitments WHERE source_memory_id=?",
                              (memory_id,))
            self.conn.commit()
    def purge_all(self):
        # Erase every stored trace of the wearer's world. `places` and
        # `entities` were skipped before — but a place row is a location
        # SIGNATURE (wifi/BLE fingerprint) that ProactiveEngine.on_place
        # matches on, so leaving it behind is a privacy residue after a full
        # wipe. `settings` is kept on purpose: it is device config, not memory.
        with self._lock:
            for t in ("memories","commitments","conversations","events","places","entities"):
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.commit()
            # A bare DELETE only frees SQLite pages; it does not scrub them, so
            # the "erased" text stays in the file's bytes and comes back out of
            # `dreamlayer memories export` (a raw file copy) or any backup.
            # Measured on a SECURE_DELETE-off build -- the upstream amalgamation
            # default, which python.org's macOS builds ship -- 105 plaintext
            # occurrences survived purge_all. EmberStore has VACUUMed for exactly
            # this reason; the main DB, which holds far more, did not.
            self.conn.execute("VACUUM")
