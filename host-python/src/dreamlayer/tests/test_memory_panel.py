"""test_memory_panel.py — 'your memory is a file' in the Mac panel (less-CLI):
the server exposes the memory file info + browse/export the panel drives, so an
operator never needs `dreamlayer memories`."""
from __future__ import annotations

from pathlib import Path

from dreamlayer.ai_brain.server.server import (
    _memory_browse, _memory_export, _memory_file,
)
from dreamlayer.ai_brain.server.panel import render_panel


class _FakeBrain:
    def __init__(self, cfg_dir):
        self.cfg_dir = Path(cfg_dir)


def _db(tmp_path, data=b"SQLite format 3\x00mem"):
    p = tmp_path / "dreamlayer.db"
    p.write_bytes(data)
    return p


def test_memory_file_reports_path_and_size(tmp_path, monkeypatch):
    monkeypatch.delenv("DREAMLAYER_DB", raising=False)
    db = _db(tmp_path)
    info = _memory_file(_FakeBrain(tmp_path))
    assert info["exists"] and info["path"] == str(db) and info["bytes"] > 0
    assert "datasette serve" in info["browse_cmd"]


def test_memory_file_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("DREAMLAYER_DB", raising=False)
    info = _memory_file(_FakeBrain(tmp_path))
    assert info["exists"] is False and info["bytes"] == 0


def test_memory_export_copies_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DREAMLAYER_DB", raising=False)
    _db(tmp_path, b"data")
    dest = tmp_path / "out" / "copy.db"
    r = _memory_export(_FakeBrain(tmp_path), str(dest))
    assert r["ok"] and dest.exists() and dest.read_bytes() == b"data"


def test_memory_export_refuses_when_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("DREAMLAYER_DB", raising=False)
    r = _memory_export(_FakeBrain(tmp_path), str(tmp_path / "x.db"))
    assert r["ok"] is False


def test_memory_browse_without_datasette_returns_the_command(tmp_path, monkeypatch):
    monkeypatch.delenv("DREAMLAYER_DB", raising=False)
    _db(tmp_path)
    r = _memory_browse(_FakeBrain(tmp_path))
    assert r["available"] is False and "datasette serve" in r["command"]


def test_panel_html_has_the_memory_section():
    html = render_panel(token="t")
    assert "Your memory is a file" in html
    assert "browseMemory()" in html and "exportMemory()" in html
