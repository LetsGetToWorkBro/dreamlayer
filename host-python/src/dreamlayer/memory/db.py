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
    def __init__(self, path: str = ":memory:", privacy=None):
        # `privacy` makes the Veil a TYPE INVARIANT on the write path rather
        # than a convention every caller has to remember (`typed_models`).
        #
        # Today every site that writes a memory checks `allow_capture()` first,
        # and this store checks nothing — the guarantee rests entirely on nobody
        # ever forgetting. That is the same shape as `person_guard`/`voice_guard`
        # before they were centralised: a rule enforced at N call sites is a rule
        # that holds until the N+1th.
        #
        # With a gate supplied, `add_memory` builds a
        # `models_pydantic.MemoryEvent(allowed=gate.allow_capture())` before it
        # writes, and that type refuses to exist when capture is disallowed. The
        # write then cannot happen — not because the caller checked, but because
        # the record cannot be constructed.
        #
        # Default None keeps today's behaviour byte-for-byte, so no existing
        # caller or test changes; it is a tripwire the Brain opts into.
        self._privacy = privacy
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

    def _scrub_tree(self, obj, _depth: int = 0):
        """`_scrub` applied through a nested dict/list, for columns that hold JSON.

        Bounded depth so a crafted payload can't recurse without limit; keys are
        scrubbed as well as values, because a caller can put text in either."""
        if _depth > 6:
            return obj
        if isinstance(obj, str):
            return self._scrub(obj)
        if isinstance(obj, dict):
            return {self._scrub(k) if isinstance(k, str) else k:
                    self._scrub_tree(v, _depth + 1) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._scrub_tree(v, _depth + 1) for v in obj]
        return obj

    def set_privacy(self, gate) -> None:
        """Attach the Veil gate after construction.

        The Orchestrator builds its `MemoryDB` before its `PrivacyGate` exists
        (`_init_core` vs the gate a few lines later), and reordering that spine
        for this would be a bigger change than the guarantee is worth. An
        explicit setter beats reaching into `_privacy` from outside.
        """
        self._privacy = gate

    def _veil_check(self, kind, summary, confidence) -> None:
        """Refuse a write the Veil forbids, by CONSTRUCTING the record type.

        The check is `MemoryEvent(...)` raising, not an `if` — that is the whole
        point of `memory/models_pydantic.py`, whose first line is "a MemoryEvent
        literally cannot be constructed with allowed=False". Routing the write
        through it means the invariant lives in one type instead of in every
        caller's memory.

        No-op without a gate, so nothing that exists today changes.

        Fails CLOSED on an unreadable posture, like every other gate in this
        product: a trust signal that cannot be read is a veiled one, and the
        write is refused rather than allowed on the benefit of the doubt.

        Raises rather than dropping quietly, deliberately. A silent refusal here
        would be a memory the wearer believes was kept and was not — worse than
        the exception, which reaches whatever already wraps the caller. Every
        production write site is veil-checked already, so this is a tripwire for
        a NEW site that forgot, not a path expected to fire.
        """
        if self._privacy is None:
            return
        from .models_pydantic import MemoryEvent
        try:
            allowed = bool(self._privacy.allow_capture())
        except Exception:                          # noqa: BLE001 — unreadable → veiled
            allowed = False
        # Deliberately NOT passing `summary`: the summary is captured content and
        # this object exists only to be refused or discarded. Nothing is gained
        # by copying the wearer's words into a validation record.
        MemoryEvent(kind=str(kind or "Note"), confidence=float(confidence or 0.0),
                    allowed=allowed)

    def add_memory(self, kind, summary, embedding=None, confidence=0.5, place_id=None, meta=None) -> int:
        self._veil_check(kind, summary, confidence)
        summary = self._scrub(summary)
        # `meta` is caller text too, and `IngestPipeline.ingest` puts the whole
        # utterance in it (`meta["task"]`), so a card number scrubbed out of
        # `summary` sat verbatim in `meta` one column over. Scrubbing the summary
        # alone made the redaction look like it worked.
        meta = self._scrub_tree(meta)
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
        # All three are caller text. `person` and `due` come from the same parsed
        # utterance as `task`, so scrubbing only `task` left two columns open.
        task = self._scrub(task)
        person = self._scrub(person)
        due = self._scrub(due)
        with self._lock:
            c = self.conn.execute("INSERT INTO commitments(person,task,due,source_memory_id,confidence,created_at) VALUES (?,?,?,?,?,?)",
                (person, task, due, source_memory_id, confidence, self._now()))
            self.conn.commit(); assert c.lastrowid is not None; return c.lastrowid
    def add_place(self, name, signature=None) -> int:
        name = self._scrub(name)                  # spoken place names are caller text
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
