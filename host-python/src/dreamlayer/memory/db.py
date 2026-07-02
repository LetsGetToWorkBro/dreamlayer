from __future__ import annotations
import sqlite3, os, json
from datetime import datetime, UTC

class MemoryDB:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        schema = os.path.join(os.path.dirname(__file__), "schema.sql")
        self.conn.executescript(open(schema).read())
        self.conn.commit()
    def _now(self): return datetime.now(UTC).isoformat()
    def add_memory(self, kind, summary, embedding=None, confidence=0.5, place_id=None, meta=None) -> int:
        c = self.conn.execute("INSERT INTO memories(kind,summary,embedding,confidence,place_id,created_at,meta) VALUES (?,?,?,?,?,?,?)",
            (kind, summary, json.dumps(embedding) if embedding else None, confidence, place_id, self._now(), json.dumps(meta or {})))
        self.conn.commit(); return c.lastrowid
    def add_commitment(self, person, task, due=None, source_memory_id=None, confidence=0.5) -> int:
        c = self.conn.execute("INSERT INTO commitments(person,task,due,source_memory_id,confidence,created_at) VALUES (?,?,?,?,?,?)",
            (person, task, due, source_memory_id, confidence, self._now()))
        self.conn.commit(); return c.lastrowid
    def add_place(self, name, signature=None) -> int:
        c = self.conn.execute("INSERT INTO places(name,signature) VALUES (?,?)", (name, signature))
        self.conn.commit(); return c.lastrowid
    def memories(self, kind=None):
        q = "SELECT * FROM memories" + (" WHERE kind=?" if kind else "")
        return [dict(r) for r in self.conn.execute(q, (kind,) if kind else ()).fetchall()]
    def commitments(self, person=None):
        q = "SELECT * FROM commitments" + (" WHERE person=?" if person else "")
        return [dict(r) for r in self.conn.execute(q, (person,) if person else ()).fetchall()]
    def places(self): return [dict(r) for r in self.conn.execute("SELECT * FROM places").fetchall()]
    def purge_memory(self, memory_id: int): self.conn.execute("DELETE FROM memories WHERE id=?", (memory_id,)); self.conn.commit()
    def purge_all(self):
        for t in ("memories","commitments","conversations","events"): self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()
