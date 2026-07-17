"""Revert-failing regressions for the 2026-07-15 audit of the new additions
(Windows Brain, the primary-API presets/discovery, the Open Library connector,
the Juno reply card, zeroconf discovery, and logging).

Each test asserts the LEAK/BREAK is closed, so reverting the fix fails it. Six
independent refutation auditors surfaced the leads; every one below was verified
in the merged code before the fix landed.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import types
import urllib.request

import pytest

# ---------------------------------------------------------------------------
# 1. Windows calendar_ics: arbitrary-file read + SSRF + OOM  (auditor A)
# ---------------------------------------------------------------------------
from dreamlayer.ai_brain.server import windows_sources as ws


def _cfg(**kw):
    return types.SimpleNamespace(calendar_ics=kw.get("calendar_ics", []),
                                 lan_only=kw.get("lan_only", False))


def test_calendar_ics_refuses_paths_outside_the_allow_list(tmp_path):
    # SECURITY (revert-failing): a calendar_ics entry pointing outside the
    # user's own tree (here /etc/hosts) must NOT be read — else a token holder
    # exfiltrates arbitrary files via /dreamlayer/calendar.
    if sys.platform == "win32":
        pytest.skip("posix system path")
    allowed = tmp_path / "mine.ics"          # tmp_path is under the temp root → allowed
    allowed.write_text("BEGIN:VCALENDAR\nEND:VCALENDAR\n")
    out = ws.load_ics_sources(_cfg(calendar_ics=[str(allowed), "/etc/hosts"]))
    names = {n for n, _ in out}
    assert "mine" in names                    # the allowed file is read
    assert not any("hosts" in n for n in names)   # /etc/hosts is refused
    assert all("root" not in text.lower() and "localhost" not in text.lower()
               for _, text in out if "hosts" not in _)


def test_calendar_ics_refuses_ssrf_targets_and_cleartext(tmp_path):
    # SECURITY (revert-failing): calendar_ics URL feeds must be PUBLIC https —
    # a loopback / link-local / RFC-1918 URL (cloud metadata!) or cleartext http
    # must never be fetched.
    called: list[str] = []

    def spy_fetch(url):
        called.append(url)
        return "BEGIN:VCALENDAR\nEND:VCALENDAR\n"

    blocked = [
        "http://169.254.169.254/latest/meta-data/",   # cloud metadata
        "http://127.0.0.1:9/cal.ics",                  # own loopback
        "http://10.0.0.5/cal.ics", "http://192.168.1.9/cal.ics",  # RFC-1918
        "http://cal.example.com/x.ics",                # cleartext public
    ]
    ws.load_ics_sources(_cfg(calendar_ics=blocked), fetcher=spy_fetch)
    assert called == []                        # not one request left the device

    ws.load_ics_sources(_cfg(calendar_ics=["https://cal.example.com/x.ics"]),
                        fetcher=spy_fetch)
    assert called == ["https://cal.example.com/x.ics"]   # public https is allowed


def test_ics_reads_are_size_capped(tmp_path):
    # DoS (revert-failing): the .ics read is bounded so a huge file can't OOM
    # the sync thread.
    big = tmp_path / "big.ics"
    big.write_bytes(b"x" * 5000)
    assert len(ws._read_ics_file(big, cap=100)) == 100
    assert ws.ICS_MAX_BYTES <= 8_000_000       # a sane cap exists


# ---------------------------------------------------------------------------
# 2. BrainConfig.save is atomic — a torn write can't drop Incognito (auditor A)
# ---------------------------------------------------------------------------
from dreamlayer.ai_brain.server import store as store_mod
from dreamlayer.ai_brain.server.store import BrainConfig


def test_config_save_is_atomic_incognito_survives_a_failed_write(tmp_path, monkeypatch):
    # SECURITY (revert-failing): a write interrupted mid-flight must leave the
    # previous config intact — never a torn file that load() silently replaces
    # with defaults (network_mode → "connected", i.e. Incognito dropped).
    BrainConfig(network_mode="lan_only", model="ollama").save(tmp_path)   # v1
    assert BrainConfig.load(tmp_path).lan_only is True

    def boom(src, dst, **kw):
        raise OSError("crash mid-replace")
    monkeypatch.setattr(store_mod, "replace_atomic", boom)
    try:
        BrainConfig(network_mode="connected", model="keyword").save(tmp_path)
    except OSError:
        pass
    reloaded = BrainConfig.load(tmp_path)
    assert reloaded.lan_only is True           # v1 intact — incognito survived
    assert reloaded.model == "ollama"
    assert not list(tmp_path.glob("*.tmp"))    # failed swap left no torn residue
    monkeypatch.undo()                          # restore the real atomic replace
    BrainConfig(network_mode="lan_only").save(tmp_path)
    assert not list(tmp_path.glob("*.tmp"))    # clean path leaves none either


# ---------------------------------------------------------------------------
# 3. Open Library rating is clamped — a spoofed response can't poison (auditor C)
# ---------------------------------------------------------------------------
from dreamlayer.plugins.openlibrary import parse_book


def test_openlibrary_rating_is_clamped_and_finite():
    # SECURITY (revert-failing): rating feeds the taste ranking AND the "N★" HUD
    # string; an untrusted/MITM'd response must not force a book to win with
    # 999999★ or inf★.
    assert parse_book({"ratings_average": 999999, "ratings_count": 3})["rating"] == 5.0
    assert parse_book({"ratings_average": -8, "ratings_count": 3})["rating"] == 0.0
    assert "rating" not in parse_book({"ratings_average": 1e400, "ratings_count": 3})
    assert "rating" not in parse_book({"ratings_average": "nope", "ratings_count": 3})
    assert parse_book({"ratings_average": 4.2, "ratings_count": 3})["rating"] == 4.2


# ---------------------------------------------------------------------------
# 4. Juno reply card can't overflow the glass with untrusted text (auditor E)
# ---------------------------------------------------------------------------
from dreamlayer.hud import renderer as R


class _RecordDraw:
    def __init__(self):
        self.texts = []

    def text(self, xy, s, **kw):
        self.texts.append((xy, s))


def test_multiline_text_caps_lines_and_breaks_long_words():
    # SECURITY (revert-failing): an untrusted remote-brain reply (thousands of
    # words, or one unbroken run) must not paint ~190 lines over the whole face.
    rr = R.CardRenderer()
    d = _RecordDraw()
    rr._multiline_text(d, 128, 132, "word " * 3000, "md", 0xFFFFFF, max_width=182)
    assert 0 < len(d.texts) <= 8               # capped to max_lines
    ys = [xy[1] for xy, _ in d.texts]
    assert all(-40 <= y <= 300 for y in ys)    # every line lands on/near the glass

    d2 = _RecordDraw()
    rr._multiline_text(d2, 128, 132, "x" * 5000, "md", 0xFFFFFF, max_width=182)
    assert 0 < len(d2.texts) <= 8              # a single 5000-char run is broken+capped


def test_juno_reply_card_renders_a_bounded_image_for_a_giant_reply():
    rr = R.CardRenderer()
    img = rr.render({"type": "JunoReplyCard", "primary": "spill " * 4000})
    assert img.size == (256, 256)              # never raises, never spills


# ---------------------------------------------------------------------------
# 5. zeroconf never broadcasts the pairing token in the TXT record (auditor E)
# ---------------------------------------------------------------------------
from dreamlayer.orchestrator import discovery_zeroconf as dz


def test_zeroconf_advertise_never_publishes_the_token(monkeypatch):
    # SECURITY (revert-failing): the pairing token must not ride in the
    # unauthenticated multicast TXT record.
    captured = {}

    def fake_service_info(service, name, addresses=None, port=None, properties=None):
        captured["properties"] = properties
        return object()

    class FakeZC:
        def register_service(self, info):
            pass

        def close(self):
            pass

    monkeypatch.setattr(dz, "_HAS_ZC", True, raising=False)
    monkeypatch.setattr(dz, "ServiceInfo", fake_service_info, raising=False)
    monkeypatch.setattr(dz, "Zeroconf", FakeZC, raising=False)

    d = dz.Discovery() if hasattr(dz, "Discovery") else dz.ZeroconfDiscovery()
    ok = d.advertise(7777, token="rune-birch-secret")
    assert ok is True
    assert captured["properties"] == {}        # nothing published…
    assert "rune-birch-secret" not in json.dumps(captured["properties"])   # …least of all the token


# ---------------------------------------------------------------------------
# 6. logging redacts sensitive keys NESTED under a benign key (auditor E)
# ---------------------------------------------------------------------------
from dreamlayer.logging_setup import JsonLineFormatter


def test_logging_redacts_nested_sensitive_values():
    # SECURITY (revert-failing): a transcript/name nested under a benign extra
    # key must be redacted, not serialised verbatim (the _sanitize wiring was
    # dead code).
    fmt = JsonLineFormatter()
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "turn", (), None)
    rec.result = {"name": "Alice Zylberberg", "transcript": "the merger closes Friday",
                  "count": 3}
    out = fmt.format(rec)
    assert "Alice Zylberberg" not in out
    assert "the merger closes Friday" not in out
    assert "<redacted:" in out
    assert '"count":3' in out or '"count": 3' in out   # benign fields survive


# ---------------------------------------------------------------------------
# 7. "Test connection" obeys the egress contract for a REMOTE endpoint (auditor B)
# ---------------------------------------------------------------------------
from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server import backends as be


def _serve(cfg_dir):
    brain = Brain(cfg_dir)
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return brain, server, f"http://127.0.0.1:{server.server_address[1]}"


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read() or b"{}")


def test_remote_test_connection_is_silenced_while_incognito(tmp_path):
    # SECURITY (revert-failing): a remote-endpoint "Test connection" must be
    # refused while incognito — before, it fired the wearer's API key to the
    # remote host anyway, contradicting the panel's own promise.
    brain, server, url = _serve(tmp_path)
    try:
        brain.config.api_provider = "custom"
        brain.config.api_base_url = "https://remote.example.com"
        brain.config.network_mode = "lan_only"          # incognito
        r = _post(url + "/dreamlayer/api/test", {})
        assert r["ok"] is False and "incognito" in r["error"].lower()
        assert brain.config.cloud_calls == 0            # nothing left the device
    finally:
        server.shutdown()


def test_remote_test_connection_counts_egress_when_not_incognito(tmp_path, monkeypatch):
    brain, server, url = _serve(tmp_path)
    try:
        monkeypatch.setattr(be, "api_chat", lambda *a, **k: "OK")   # no real network
        brain.config.api_provider = "custom"
        brain.config.api_base_url = "https://remote.example.com"
        brain.config.network_mode = "connected"
        before = brain.config.cloud_calls
        r = _post(url + "/dreamlayer/api/test", {})
        assert r["ok"] is True
        assert brain.config.cloud_calls == before + 1   # counted as egress
    finally:
        server.shutdown()


def test_local_test_connection_is_not_counted_as_egress(tmp_path, monkeypatch):
    brain, server, url = _serve(tmp_path)
    try:
        monkeypatch.setattr(be, "api_chat", lambda *a, **k: "OK")
        brain.config.api_provider = "custom"
        brain.config.api_base_url = "http://localhost:1234/v1"      # on-device
        brain.config.network_mode = "connected"
        before = brain.config.cloud_calls
        r = _post(url + "/dreamlayer/api/test", {})
        assert r["ok"] is True
        assert brain.config.cloud_calls == before        # local = free, not egress
    finally:
        server.shutdown()
