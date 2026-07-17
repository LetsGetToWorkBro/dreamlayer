"""test_memory_panel.py — 'your memory is a file' in the Mac panel (less-CLI):
the server exposes the memory file info + browse/export the panel drives, so an
operator never needs `dreamlayer memories`."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dreamlayer.ai_brain.server.server import (
    _memory_browse, _memory_export, _memory_file,
)
from dreamlayer.ai_brain.server.backends import is_local_endpoint
from dreamlayer.ai_brain.server.panel import render_panel


def _find_node():
    for cand in ("/opt/node22/bin/node", "node", "nodejs"):
        if "/" in cand:
            if Path(cand).exists():
                return cand
        else:
            found = shutil.which(cand)
            if found:
                return found
    return None


# Adversarial inputs for the isLocalUrl parity test. Python is_local_endpoint is
# the source of truth; the served JS must never say "local" (green) where Python
# says remote. Includes the 7 divergences the 2026-07-17 refute wave found.
_ISLOCAL_INPUTS = [
    "http://localhost", "http://localhost:1234/v1", "http://127.0.0.1",
    "http://127.0.0.1:8080", "http://10.0.0.5", "http://192.168.1.5",
    "http://172.16.0.1", "http://172.32.0.1", "http://169.254.1.1",
    "http://[::1]", "http://[::1]:8080", "http://foo.local",
    "http://8.8.8.8", "http://evil.com", "http://localhost@evil.com",
    "http://evil.com@localhost", "http://localhost.", "https://LOCALHOST",
    "http://010.0.0.1", "http://10.999.0.0", "http://127.1",
    "http://2130706433", "http://0x7f000001", "http://", "",
    "http://local\thost",
    # the 7 known false-green divergences:
    "http://ｌｏｃａｌｈｏｓｔ",   # fullwidth "localhost"
    "http://ｌｏｃａｌｈｏｓｔ:8080",
    "http://ｅｖｉｌ．ｌｏｃａｌ",  # fullwidth "evil.local"
    "http://evil．local",                                          # fullwidth dot
    "http:\\localhost\\evil.com", "http:/localhost", "http:localhost",
    # bracketed-host false-greens (Python urlsplit rejects a bracketed name/IPv4
    # and any junk after "]"; only a clean [::1] is local):
    "http://[localhost]", "http://[foo.local]", "http://[127.0.0.1]",
    "http://[10.0.0.1]", "http://[192.168.1.1]", "http://[::1]extra",
    "http://[::1].local", "http://[::1]]", "http://[::ffff:127.0.0.1]",
    "http://[fe80::1]",
]
_ISLOCAL_LOCAL_FORMS = [
    "http://localhost", "http://localhost:1234/v1", "http://127.0.0.1",
    "http://10.0.0.5", "http://192.168.1.5", "http://172.16.0.1",
    "http://169.254.1.1", "http://[::1]", "http://foo.local",
]
_ISLOCAL_DIVERGENCES = [
    "http://ｌｏｃａｌｈｏｓｔ",
    "http://ｌｏｃａｌｈｏｓｔ:8080",
    "http://ｅｖｉｌ．ｌｏｃａｌ",
    "http://evil．local",
    "http:\\localhost\\evil.com", "http:/localhost", "http:localhost",
]


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


def test_panel_islocalurl_matches_python_is_local_endpoint():
    """The panel banner's isLocalUrl must never show "on your device" (green) for
    a host backends.is_local_endpoint counts as REMOTE egress — the wearer reads
    that banner to decide whether a query leaves the device. Reading
    new URL().hostname diverged on 7 adversarial inputs (fullwidth homoglyphs like
    ``http://ｌｏｃａｌｈｏｓｔ`` that IDNA-fold to "localhost", and
    non-"//" scheme forms like ``http:localhost``), showing green for a host the
    server treats as egress (audit 2026-07-17). The JS now mirrors
    urllib.urlsplit host extraction. This runs the SERVED JS in node against the
    Python classifier and asserts: (a) safety — JS true only where Python is
    local; (b) coverage — the common local forms render green; (c) the 7
    divergences no longer read green. Skipped when node is unavailable.
    FAILS ON REVERT to the new URL().hostname classifier."""
    node = _find_node()
    if not node:
        pytest.skip("no node runtime to exercise the served panel JS")
    html = render_panel(token="t")
    start = html.find("function isLocalUrl")
    assert start != -1
    fn = html[start:html.find("const APROV", start)].strip()
    harness = (fn + "\nconst ins=" + json.dumps(_ISLOCAL_INPUTS)
               + ";console.log(JSON.stringify(ins.map(isLocalUrl)));")
    out = subprocess.run([node, "-e", harness], capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    js = json.loads(out.stdout)
    # (a) SAFETY: never green for a host Python classifies remote.
    for u, j in zip(_ISLOCAL_INPUTS, js):
        if is_local_endpoint(u) is False:
            assert j is not True, f"false-green: JS said local for remote {u!r}"
    # (b) COVERAGE: the everyday local forms still read green.
    for u in _ISLOCAL_LOCAL_FORMS:
        assert js[_ISLOCAL_INPUTS.index(u)] is True, f"real-local not green: {u!r}"
    # (c) the 7 known divergences no longer read green.
    for u in _ISLOCAL_DIVERGENCES:
        assert js[_ISLOCAL_INPUTS.index(u)] is not True, f"divergence still green: {u!r}"


def test_panel_islocalurl_ipv4_regex_is_live_not_dead():
    """Always-on guard for the raw-string escaping: the IPv4 branch must be served
    as a working ``\\d`` (single backslash), not the dead ``\\\\d`` (double), or no
    private IPv4 is ever classified local. FAILS ON REVERT to the double-backslash
    regex (this runs even where node is absent)."""
    html = render_panel(token="t")
    body = html[html.find("function isLocalUrl"):html.find("const APROV")]
    assert "\\\\d" not in body            # the dead double-backslash regex is gone
    assert "(\\d+)" in body               # a working ASCII-digit class is served
    # and the classifier no longer trusts new URL().hostname (the folding source)
    assert "new URL(u).hostname" not in body
