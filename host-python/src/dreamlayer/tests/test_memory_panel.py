"""test_memory_panel.py — 'your memory is a file' in the Mac panel (less-CLI):
the server exposes the memory file info + browse/export the panel drives, so an
operator never needs `dreamlayer memories`."""
from __future__ import annotations

import json
import re
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
    # bracket in the USERINFO: urlsplit raises ValueError -> is_local_endpoint
    # REMOTE, but the naive "host is after the last @" strip greened the address
    # after the @ (refute 2026-07-17):
    "http://[::1]@127.0.0.1", "http://[foo]@192.168.1.1", "//[::1]@10.0.0.1",
    "http://[x]@127.0.0.1", "http://[::1]@10.0.0.5",
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
    # bracket-in-userinfo false-greens (refute 2026-07-17):
    "http://[::1]@127.0.0.1", "http://[foo]@192.168.1.1", "//[::1]@10.0.0.1",
    "http://[x]@127.0.0.1", "http://[::1]@10.0.0.5",
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


# --- node-less drift protection --------------------------------------------
# The node parity test above SKIPS when no node runtime is present, so a CI leg
# without node has NO protection against the served isLocalUrl drifting from
# backends.is_local_endpoint. `_js_islocalurl_py` is a line-for-line Python
# transliteration of the served JS classifier (panel.py's isLocalUrl), kept next
# to this test and diff-tested against is_local_endpoint over a large adversarial
# corpus with plain pytest — so the dangerous divergence (classifier reads LOCAL
# while the server counts the host as REMOTE egress) is caught even where node is
# absent. The node test remains as an extra cross-check that this transliteration
# still matches the ACTUAL served JS when a runtime is available.
_JS_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://")
# ASCII-only digit class, mirroring JS `\d` (no unicode flag) EXACTLY — Python's
# own `\d` matches fullwidth digits, which would defeat the homoglyph defence.
_JS_V4_RE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)\.([0-9]+)$")


def _js_islocalurl_py(u):
    """Transliteration of panel.py's served ``isLocalUrl``. Returns True (local),
    False (remote), or None (empty / no ``//`` authority — 'unknown'), exactly as
    the JS does. Mirror any edit to the served JS here, or the node test (when a
    runtime is present) will flag the two out of sync."""
    u = re.sub(r"[\t\r\n]", "", u or "")           # urlsplit strips these too
    if not u:
        return None                                 # empty — still typing
    rest = None
    sm = _JS_SCHEME_RE.match(u)
    if sm:
        rest = u[sm.end():]                          # scheme://authority
    elif u[:2] == "//":
        rest = u[2:]                                 # //authority (scheme-relative)
    if rest is None:
        return None                                  # no "//" authority
    auth = rest.split("/")[0].split("?")[0].split("#")[0]
    at = auth.rfind("@")
    if at >= 0:
        ui = auth[:at]
        if "[" in ui or "]" in ui:                   # bracket in userinfo -> ValueError -> remote
            return False
        auth = auth[at + 1:]                         # host is after the last @
    if auth[:1] == "[":
        e = auth.find("]")
        if e < 0:
            return False                             # unterminated bracket -> remote
        after = auth[e + 1:]
        if after != "" and after[:1] != ":":         # junk after "]" -> ValueError -> remote
            return False
        return auth[1:e].lower() == "::1"            # loopback IPv6 only
    host = auth.split(":")[0].lower()                # drop :port
    if not host:
        return False
    if host == "localhost" or host.endswith(".local"):
        return True
    m = _JS_V4_RE.match(host)
    if m:
        octets = [m.group(1), m.group(2), m.group(3), m.group(4)]
        for part in octets:
            if len(part) > 1 and part[0] == "0":     # leading zero -> Python rejects -> remote
                return False
            if int(part) > 255:                      # >255 -> remote
                return False
        a, b = int(octets[0]), int(octets[1])
        return (a == 127 or a == 10 or (a == 192 and b == 168)
                or (a == 172 and 16 <= b <= 31) or (a == 169 and b == 254))
    return False                                     # public / bare host -> remote


# The adversarial corpus: every family the parity test exercises — fullwidth
# homoglyphs, bracketed IPv6, userinfo @/bracket, octal/hex/decimal IP forms,
# leading-zero / >255 octets, scheme-relative "//", trailing-dot — plus the
# module's own _ISLOCAL_INPUTS, deduped.
_ISLOCAL_CORPUS = list(dict.fromkeys(_ISLOCAL_INPUTS + [
    # scheme-relative authorities
    "//localhost", "//127.0.0.1", "//10.0.0.5", "//192.168.1.1", "//evil.com",
    # octal / hex / decimal / short IPv4 spellings
    "http://0177.0.0.1", "http://0x7f.0.0.1", "http://127.0.0.256",
    "http://256.0.0.1", "http://0.0.0.0", "http://192.168.001.1",
    "http://2130706433/x", "http://0x7f000001:80",
    # RFC-1918 boundary octets (just-in / just-out)
    "http://172.15.0.1", "http://172.31.255.255", "http://172.32.0.1",
    "http://192.169.0.1", "http://169.253.0.1", "http://11.0.0.1",
    # trailing-dot and localhost-suffix tricks
    "http://localhost.evil.com", "http://notlocalhost", "http://a.local.",
    "http://127.0.0.1.", "http://foo.local.evil.com",
    # fullwidth-digit IPv4 (Python \d would fold these; JS \d must not)
    "http://１２７.0.0.1", "http://127.０.0.1", "http://ff02::1",
    # bracket / userinfo edge forms
    "http://user:pass@127.0.0.1", "http://user@localhost", "http://[]",
    "http://[:]", "http://[::]", "http://[::1]:", "http://[::1]/x",
    "http://[::1]:99999", "http://[fe80::1%25eth0]", "http://[::ffff:10.0.0.1]",
    # scheme / whitespace / junk
    "HTTP://LOCALHOST", "ftp://127.0.0.1", "wss://localhost", "hxxp://localhost",
    "javascript:alert(1)", "  http://localhost", "http://LoCaLhOsT",
    "http://10.0.0.5?x=1", "http://10.0.0.5#f", "mailto:a@localhost",
]))


def test_panel_islocalurl_transliteration_never_false_green_nodeless():
    """Node-less drift guard: the Python transliteration of the served isLocalUrl
    must NEVER read LOCAL where backends.is_local_endpoint reads REMOTE — the
    dangerous direction, where the banner would tell the wearer a query stays on
    device while the server actually treats the host as cloud egress. Runs on
    plain pytest (no node), so the node-less CI leg is protected. FAILS if the
    transliteration (kept in sync with the served JS) ever greens a remote host."""

    def false_greens(classifier):
        return [u for u in _ISLOCAL_CORPUS
                if classifier(u) is True and is_local_endpoint(u) is False]

    # the guard itself: no false-greens anywhere in the corpus.
    assert false_greens(_js_islocalurl_py) == []
    # teeth: the corpus really does contain remote hosts, so a classifier that
    # greened everything WOULD be caught — proving the assertion isn't vacuous.
    assert false_greens(lambda u: True), "corpus has no remote inputs to catch"
    # coverage: the everyday local forms still read LOCAL in the transliteration.
    for u in _ISLOCAL_LOCAL_FORMS:
        assert _js_islocalurl_py(u) is True, f"real-local not local: {u!r}"
    # and the known homoglyph/scheme divergences never read LOCAL.
    for u in _ISLOCAL_DIVERGENCES:
        assert _js_islocalurl_py(u) is not True, f"divergence reads local: {u!r}"


def test_panel_islocalurl_transliteration_matches_served_js_when_node_present():
    """Cross-check (only when node is available): the Python transliteration above
    must classify the whole corpus BYTE-IDENTICALLY to the ACTUAL served JS, so a
    JS edit that isn't mirrored into the transliteration is caught. Skipped
    node-less — the transliteration test above carries the node-less leg."""
    node = _find_node()
    if not node:
        pytest.skip("no node runtime to exercise the served panel JS")
    html = render_panel(token="t")
    start = html.find("function isLocalUrl")
    fn = html[start:html.find("const APROV", start)].strip()
    harness = (fn + "\nconst ins=" + json.dumps(_ISLOCAL_CORPUS)
               + ";console.log(JSON.stringify(ins.map(isLocalUrl)));")
    out = subprocess.run([node, "-e", harness], capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    js = json.loads(out.stdout)
    for u, jr in zip(_ISLOCAL_CORPUS, js):
        assert _js_islocalurl_py(u) == jr, (
            f"transliteration drift on {u!r}: python={_js_islocalurl_py(u)!r} "
            f"served-js={jr!r} — update _js_islocalurl_py to match panel.py")
