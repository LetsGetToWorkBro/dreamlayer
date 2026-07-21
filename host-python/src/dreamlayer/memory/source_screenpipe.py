"""memory/source_screenpipe.py — the Brain remembers your screen (screenpipe).

The glasses will remember the world; until Halo ships, screenpipe
(mediar-ai/screenpipe) remembers your screen: 24/7 local capture of screen OCR
and audio transcription, all data on-device in a SQLite file. This source reads
that file DIRECTLY — no server, no socket, read-only — and folds the rows into
the Brain's memory stream, so "what was that dashboard I had open on Tuesday"
becomes a recall query.

Posture: everything stays local. The DB is opened read-only (`mode=ro`), we
never write to screenpipe's store, and nothing here makes a network call.
screenpipe's schema has evolved across releases, so table/column discovery is
defensive: any missing table or renamed column simply yields fewer rows, never
an error. No wheel needed — stdlib sqlite3 — so `available` reflects only
whether the screenpipe DB actually exists on this machine.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("dreamlayer.screenpipe")

_MAX_TEXT = 800          # keep a memory row a sentence-scale snippet, not a page


def default_db_path() -> Path:
    """screenpipe's default store: ~/.screenpipe/db.sqlite ($SCREENPIPE_DIR to
    override, matching their env var)."""
    root = os.environ.get("SCREENPIPE_DIR") or str(Path.home() / ".screenpipe")
    return Path(root) / "db.sqlite"


class ScreenpipeSource:
    """Read screenpipe's local DB as a memory source. `available` is True only
    when the DB file exists (i.e. the user actually runs screenpipe)."""

    def __init__(self, db_path: Optional[str] = None):
        self.path = Path(db_path) if db_path else default_db_path()

    @property
    def available(self) -> bool:
        try:
            return self.path.is_file()
        except OSError:
            return False

    def _connect(self):
        # read-only URI so a Brain bug can never corrupt screenpipe's store
        uri = f"file:{self.path}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=1.0)

    def _tables(self, con) -> set:
        try:
            rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            return {r[0] for r in rows}
        except sqlite3.Error:
            return set()

    def _columns(self, con, table: str) -> set:
        try:
            return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        except sqlite3.Error:
            return set()

    def recent(self, limit: int = 50, since_ts: float = 0.0) -> List[dict]:
        """Newest screen/audio snippets as memory rows:
        {ts, kind: "screen"|"audio", text, app}. [] when unavailable or on any
        schema surprise — never raises into the ingest loop."""
        if not self.available:
            return []
        limit = max(1, min(int(limit), 500))
        out: List[dict] = []
        try:
            with self._connect() as con:
                tables = self._tables(con)
                out.extend(self._screen_rows(con, tables, limit, since_ts))
                out.extend(self._audio_rows(con, tables, limit, since_ts))
        except Exception as exc:                   # noqa: BLE001
            log.info("[screenpipe] read failed: %s", exc)
            return []
        out.sort(key=lambda r: -r["ts"])
        return out[:limit]

    def _screen_rows(self, con, tables, limit, since_ts) -> List[dict]:
        if "ocr_text" not in tables or "frames" not in tables:
            return []
        cols = self._columns(con, "ocr_text")
        app = "app_name" if "app_name" in cols else None
        try:
            q = ("SELECT f.timestamp, o.text" +
                 (f", o.{app}" if app else ", ''") +
                 " FROM ocr_text o JOIN frames f ON f.id = o.frame_id"
                 " ORDER BY f.timestamp DESC LIMIT ?")
            rows = con.execute(q, (limit,)).fetchall()
        except sqlite3.Error as exc:
            log.debug("[screenpipe] ocr query failed: %s", exc)
            return []
        return [r for r in (self._row(ts, "screen", txt, appn)
                            for ts, txt, appn in rows)
                if r is not None and r["ts"] >= since_ts]

    def _audio_rows(self, con, tables, limit, since_ts) -> List[dict]:
        if "audio_transcriptions" not in tables:
            return []
        cols = self._columns(con, "audio_transcriptions")
        tcol = "transcription" if "transcription" in cols else None
        tscol = "timestamp" if "timestamp" in cols else None
        if not tcol or not tscol:
            return []
        try:
            rows = con.execute(
                f"SELECT {tscol}, {tcol} FROM audio_transcriptions"
                f" ORDER BY {tscol} DESC LIMIT ?", (limit,)).fetchall()
        except sqlite3.Error as exc:
            log.debug("[screenpipe] audio query failed: %s", exc)
            return []
        return [r for r in (self._row(ts, "audio", txt, "") for ts, txt in rows)
                if r is not None and r["ts"] >= since_ts]

    @staticmethod
    def _row(ts, kind, text, app) -> Optional[dict]:
        text = str(text or "").strip()
        if not text:
            return None
        try:
            # screenpipe stores ISO-8601 strings or unix floats depending on era
            if isinstance(ts, str):
                import datetime as _dt
                ts = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            ts = float(ts)
        except (ValueError, TypeError):
            return None
        return {"ts": ts, "kind": kind, "text": text[:_MAX_TEXT],
                "app": str(app or "")}


def default_screen_source() -> Optional[ScreenpipeSource]:
    s = ScreenpipeSource()
    return s if s.available else None
