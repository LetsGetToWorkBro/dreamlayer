"""memory sources: screenpipe (local SQLite) + ActivityWatch (loopback REST).

Neither app runs in CI, so screenpipe is tested against a synthetic DB in both
schema eras, and ActivityWatch against an injected fetch seam. Both pin the
[]-never-raise contract and the read-only / loopback-only posture.
"""
from __future__ import annotations

import json
import sqlite3

from dreamlayer.memory.source_activitywatch import ActivityWatchSource, default_desk_source
from dreamlayer.memory.source_screenpipe import ScreenpipeSource, default_screen_source


def _make_db(path, iso_ts=False):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE frames (id INTEGER PRIMARY KEY, timestamp)")
    con.execute("CREATE TABLE ocr_text (frame_id INTEGER, text TEXT, app_name TEXT)")
    con.execute("CREATE TABLE audio_transcriptions (transcription TEXT, timestamp)")
    ts1 = "2026-07-20T10:00:00Z" if iso_ts else 1_752_900_000.0
    ts2 = "2026-07-20T11:00:00Z" if iso_ts else 1_752_903_600.0
    con.execute("INSERT INTO frames VALUES (1, ?)", (ts1,))
    con.execute("INSERT INTO frames VALUES (2, ?)", (ts2,))
    con.execute("INSERT INTO ocr_text VALUES (1, 'Quarterly numbers dashboard', 'Safari')")
    con.execute("INSERT INTO ocr_text VALUES (2, '', 'Finder')")          # empty → dropped
    con.execute("INSERT INTO audio_transcriptions VALUES ('standup notes', ?)", (ts2,))
    con.commit()
    con.close()


class TestScreenpipe:
    def test_missing_db_is_unavailable_and_empty(self, tmp_path):
        s = ScreenpipeSource(str(tmp_path / "nope.sqlite"))
        assert s.available is False
        assert s.recent() == []

    def test_reads_screen_and_audio_rows(self, tmp_path):
        db = tmp_path / "db.sqlite"
        _make_db(db)
        s = ScreenpipeSource(str(db))
        rows = s.recent()
        kinds = {r["kind"] for r in rows}
        assert kinds == {"screen", "audio"}
        texts = [r["text"] for r in rows]
        assert "Quarterly numbers dashboard" in texts
        assert all(r["text"] for r in rows)          # empty snippets dropped
        # newest first
        assert rows == sorted(rows, key=lambda r: -r["ts"])

    def test_iso_timestamps_parse(self, tmp_path):
        db = tmp_path / "db.sqlite"
        _make_db(db, iso_ts=True)
        rows = ScreenpipeSource(str(db)).recent()
        assert rows and all(r["ts"] > 1_500_000_000 for r in rows)

    def test_weird_schema_degrades_to_empty(self, tmp_path):
        db = tmp_path / "db.sqlite"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE something_else (x)")
        con.commit(); con.close()
        assert ScreenpipeSource(str(db)).recent() == []

    def test_db_is_opened_read_only(self, tmp_path):
        db = tmp_path / "db.sqlite"
        _make_db(db)
        s = ScreenpipeSource(str(db))
        with s._connect() as con:
            try:
                con.execute("INSERT INTO frames VALUES (99, 0)")
                wrote = True
            except sqlite3.OperationalError:
                wrote = False
        assert wrote is False                        # mode=ro really holds

    def test_default_none_when_absent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SCREENPIPE_DIR", str(tmp_path / "empty"))
        assert default_screen_source() is None


def _aw_fetch(payloads):
    def fetch(url, timeout=2.0):
        for frag, body in payloads.items():
            if frag in url:
                return json.dumps(body).encode()
        return None
    return fetch


class TestActivityWatch:
    def test_unavailable_without_server(self):
        s = ActivityWatchSource(fetch_fn=lambda url, timeout=2.0: None)
        assert s.available is False
        assert s.recent() == []

    def test_recent_rows_from_window_bucket(self):
        payloads = {
            "/api/0/buckets/aw-watcher-window_x/events": [
                {"timestamp": "2026-07-20T10:00:00Z", "duration": 42.5,
                 "data": {"app": "Xcode", "title": "brain.swift"}},
                {"timestamp": "bad-ts", "data": {"app": "Junk"}},     # dropped
            ],
            "/api/0/buckets": {"aw-watcher-window_x": {}, "aw-watcher-afk_x": {}},
        }
        s = ActivityWatchSource(fetch_fn=_aw_fetch(payloads))
        rows = s.recent()
        assert len(rows) == 1
        assert rows[0]["app"] == "Xcode" and "brain.swift" in rows[0]["text"]
        assert rows[0]["duration"] == 42.5

    def test_non_loopback_base_is_pinned_back(self):
        s = ActivityWatchSource(base="http://8.8.8.8:5600",
                                fetch_fn=lambda url, timeout=2.0: None)
        assert s.base.startswith("http://127.0.0.1")

    def test_malformed_replies_degrade(self):
        s = ActivityWatchSource(fetch_fn=lambda url, timeout=2.0: b"{not json")
        assert s.buckets() == [] and s.recent() == []

    def test_default_none_without_server(self):
        # CI has no ActivityWatch on 5600; the loopback probe fails fast
        assert default_desk_source() is None


def test_service_capabilities_registered():
    from dreamlayer import capabilities as C
    caps = {c.key: c for c in C.CAPABILITIES}
    for key, seam in [("screen_memory", "memory/source_screenpipe.py"),
                      ("desk_memory", "memory/source_activitywatch.py")]:
        assert key in caps and caps[key].kind == "service"
        assert caps[key].seam == seam
