"""test_windows_sources.py — the Windows data sources, in the image of
test_ai_brain_macos.py: pure parsing against fixtures (Thunderbird mbox,
.ics calendars), honest absences (no iMessage, [] off-Windows), the
Incognito gate on URL feeds, and the platform-honest panel copy.
"""
from __future__ import annotations

import http.server
import threading
import time
from email.message import EmailMessage

import pytest

from dreamlayer.ai_brain.server import windows_sources as ws
from dreamlayer.ai_brain.server.store import BrainConfig


# ---------------------------------------------------------------------------
# Thunderbird mbox (fixture bytes shaped like a Local Folders store)
# ---------------------------------------------------------------------------

def _mbox_message(frm, subject, body, date="Mon, 1 Jan 2026 09:00:00 +0000"):
    m = EmailMessage()
    m["From"] = frm; m["Subject"] = subject; m["Date"] = date
    m.set_content(body)
    return b"From - Thu Jan 01 00:00:00 2026\n" + m.as_bytes()


def _mbox(*messages) -> bytes:
    return b"\n".join(messages)


class TestParseMbox:
    def test_reads_messages_in_order(self):
        raw = _mbox(_mbox_message("maya@x.com", "Lunch?", "Friday works."),
                    _mbox_message("billing@co.com", "Invoice", "Amount due: 240."))
        msgs = ws.parse_mbox(raw)
        assert [m["subject"] for m in msgs] == ["Lunch?", "Invoice"]
        assert "Friday" in msgs[0]["body"] and "240" in msgs[1]["body"]
        assert msgs[0]["ts"] > 0                      # Date header parsed

    def test_unescapes_mboxrd_from_lines(self):
        raw = _mbox_message("a@b.com", "quoting",
                            "start\n>From the beginning\nend")
        # the writer escaped the body line; the reader must restore it
        raw = raw.replace(b">From the beginning", b">>From the beginning")
        msgs = ws.parse_mbox(raw)
        assert ">From the beginning" in msgs[0]["body"]

    def test_limit_keeps_the_newest(self):
        raw = _mbox(*[_mbox_message("a@b.com", f"m{i}", "x") for i in range(5)])
        msgs = ws.parse_mbox(raw, limit=2)
        assert [m["subject"] for m in msgs] == ["m3", "m4"]

    def test_garbage_is_empty(self):
        assert ws.parse_mbox(b"") == []
        assert ws.parse_mbox(b"no separators at all") == []


class TestMailDocuments:
    def test_reads_thunderbird_profile(self, tmp_path):
        prof = tmp_path / "Profiles" / "abc.default" / "Mail" / "Local Folders"
        prof.mkdir(parents=True)
        (prof / "INBOX").write_bytes(_mbox(
            _mbox_message("maya@x.com", "Contract", "Bring the signed contract.")))
        (prof / "INBOX.msf").write_bytes(b"")        # the index sibling
        docs = ws.mail_documents(tmp_path / "Profiles")
        assert docs and "signed contract" in docs[0][1]
        assert docs[0][0].startswith("Mail · Contract")

    def test_missing_profile_is_empty(self, tmp_path):
        assert ws.mail_documents(tmp_path / "nope") == []

    def test_files_without_msf_sibling_are_ignored(self, tmp_path):
        root = tmp_path / "Profiles"; root.mkdir()
        (root / "notes.txt").write_text("not a mailbox")
        assert ws.mail_documents(root) == []


class TestHonestAbsence:
    def test_collect_documents_empty_off_windows(self):
        import platform
        if platform.system() == "Windows":
            return                                    # covered by the CI leg
        assert ws.collect_documents(BrainConfig()) == []

    def test_recent_messages_empty_off_windows(self):
        import platform
        if platform.system() == "Windows":
            return
        assert ws.recent_messages(BrainConfig()) == []

    def test_no_imessage_channel_is_ever_fabricated(self):
        # windows_sources must never emit channel:"imessage" — there is no
        # message store on Windows and the Brain does not pretend otherwise.
        import inspect
        src = inspect.getsource(ws)
        assert '"imessage"' not in src


# ---------------------------------------------------------------------------
# Calendar (.ics) — pure parser + the injectable reader seam
# ---------------------------------------------------------------------------

def _ics(*events, name="Home"):
    body = "".join(events)
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            f"X-WR-CALNAME:{name}\r\n{body}END:VCALENDAR\r\n")


def _vevent(summary, dtstart, location=""):
    loc = f"LOCATION:{location}\r\n" if location else ""
    return (f"BEGIN:VEVENT\r\nSUMMARY:{summary}\r\nDTSTART:{dtstart}\r\n"
            f"{loc}END:VEVENT\r\n")


def _utc(ts: float) -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(ts))


class TestIcsEvents:
    def test_parses_window_sorted(self):
        now = time.time()
        text = _ics(_vevent("Later", _utc(now + 7200), "Cafe"),
                    _vevent("Sooner", _utc(now + 3600)),
                    _vevent("Too far", _utc(now + 40 * 86400)))
        evs = ws.ics_events(text, now=now, days_ahead=14)
        assert [e["title"] for e in evs] == ["Sooner", "Later"]
        assert evs[1]["place"] == "Cafe"
        assert all(e["calendar"] == "Home" for e in evs)

    def test_past_events_are_dropped(self):
        now = time.time()
        text = _ics(_vevent("Old", _utc(now - 86400)),
                    _vevent("Now-ish", _utc(now + 60)))
        evs = ws.ics_events(text, now=now)
        assert [e["title"] for e in evs] == ["Now-ish"]

    def test_folded_lines_and_escapes(self):
        now = time.time()
        text = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n"
                "SUMMARY:Sign the\r\n  lease\\, finally\r\n"
                f"DTSTART:{_utc(now + 600)}\r\n"
                "END:VEVENT\r\nEND:VCALENDAR\r\n")
        evs = ws.ics_events(text, calendar="Legal", now=now)
        assert evs[0]["title"] == "Sign the lease, finally"
        assert evs[0]["calendar"] == "Legal"

    def test_all_day_and_local_times_parse(self):
        now = time.time()
        tomorrow = time.strftime("%Y%m%d", time.localtime(now + 86400))
        local = time.strftime("%Y%m%dT%H%M%S", time.localtime(now + 3600))
        text = _ics(_vevent("All day", tomorrow),
                    _vevent("Local", local))
        titles = {e["title"] for e in ws.ics_events(text, now=now)}
        assert titles == {"All day", "Local"}


class TestReadCalendarEvents:
    def test_reader_seam_works_off_windows(self):
        now = time.time()
        reader = lambda: [("Home", _ics(_vevent("Dentist", _utc(now + 3600))))]
        evs = ws.read_calendar_events(BrainConfig(), reader=reader)
        assert [e["title"] for e in evs] == ["Dentist"]
        assert evs[0]["calendar"] == "Home"

    def test_calendar_names_filter_matches_macos_semantics(self):
        now = time.time()
        reader = lambda: [
            ("Home", _ics(_vevent("Dentist", _utc(now + 3600)), name="Home")),
            ("Work", _ics(_vevent("Standup", _utc(now + 3600)), name="Work"))]
        cfg = BrainConfig(calendar_names=["Work"])
        evs = ws.read_calendar_events(cfg, reader=reader)
        assert [e["title"] for e in evs] == ["Standup"]

    def test_off_windows_without_reader_is_empty(self):
        import platform
        if platform.system() == "Windows":
            return
        assert ws.read_calendar_events(BrainConfig()) == []

    def test_list_calendars_prefers_declared_names(self):
        reader = lambda: [("feed", _ics(name="Family"))]
        assert ws.list_calendars(reader=reader) == ["Family"]


class TestIncognitoNeverFetches:
    def test_url_feeds_skipped_while_lan_only(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DREAMLAYER_DIR", str(tmp_path))
        fetched = []
        cfg = BrainConfig(network_mode="lan_only",
                          calendar_ics=["https://example.com/cal.ics"])
        out = ws.load_ics_sources(cfg, fetcher=lambda u: fetched.append(u) or "")
        assert fetched == [] and out == []

    def test_url_feeds_fetched_when_connected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DREAMLAYER_DIR", str(tmp_path))
        now = time.time()
        cfg = BrainConfig(network_mode="connected",
                          calendar_ics=["https://example.com/cal.ics"])
        payload = _ics(_vevent("Recital", _utc(now + 3600)), name="Family")
        out = ws.load_ics_sources(cfg, fetcher=lambda u: payload)
        assert out == [("cal", payload)]

    def test_local_ics_dir_is_always_read(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DREAMLAYER_DIR", str(tmp_path))
        cal = tmp_path / "calendars"; cal.mkdir()
        (cal / "home.ics").write_text(_ics(name="Home"))
        out = ws.load_ics_sources(BrainConfig(network_mode="lan_only"))
        assert [name for name, _ in out] == ["home"]

    def test_calendars_dir_symlink_escaping_allowlist_is_refused(
            self, tmp_path, monkeypatch):
        # A junction/symlink dropped in <state>/calendars that RESOLVES outside
        # the user's own tree must be refused — the `*.ics` glob lists it, but
        # every glob result flows through store._is_allowed_root (which
        # resolve()s), the same default-deny gate that guards calendar_ics file
        # entries and watched folders (audit 2026-07-17). Revert-failing: drop
        # the _is_allowed_root check on glob paths and `escape` gets read.
        import os
        from dreamlayer.ai_brain.server import store
        # Narrow the allow-list to `allowed/` so `outside/` is genuinely outside
        # the user tree (real HOME/tmp on CI both contain pytest's tmp_path).
        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir(); outside.mkdir()
        monkeypatch.setenv("HOME", str(allowed))          # POSIX Path.home()
        # Path.home() reads USERPROFILE (not HOME) on Windows, so narrow that too
        # or the escape target — which lives under the real temp/profile tree on
        # the Windows runner — stays inside the allow-list and the test can't tell
        # a refused escape from an allowed one (test-windows CI, 2026-07-17).
        monkeypatch.setenv("USERPROFILE", str(allowed))   # Windows Path.home()
        monkeypatch.delenv("HOMEDRIVE", raising=False)     # don't let these override
        monkeypatch.delenv("HOMEPATH", raising=False)
        monkeypatch.setattr(store.tempfile, "gettempdir", lambda: str(allowed))
        state = allowed / ".dreamlayer"
        cal = state / "calendars"; cal.mkdir(parents=True)
        monkeypatch.setenv("DREAMLAYER_DIR", str(state))
        # a readable .ics OUTSIDE the allow-list — the symlink's real target
        secret = outside / "secret.ics"
        secret.write_text(_ics(_vevent("Exfil", "20260101T000000Z"),
                               name="Secret"))
        (cal / "home.ics").write_text(_ics(name="Home"))  # legit, allow-listed
        try:
            os.symlink(secret, cal / "escape.ics")        # junction analogue
        except (OSError, NotImplementedError):
            import pytest
            pytest.skip("symlinks unavailable (Windows without privilege)")
        names = [name for name, _ in ws.load_ics_sources(BrainConfig())]
        assert "home" in names            # the allow-listed file is still read
        assert "escape" not in names      # the escaping junction is refused


# ---------------------------------------------------------------------------
# SSRF-via-redirect: the ICS URL fetch must refuse a 3xx bounce to another host
# (mirrors test_egress_hardening_2026_07_17 — a real in-process HTTP server so
# the test is honestly red on revert to the redirect-following default opener).
# ---------------------------------------------------------------------------

class _Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):            # keep the test run quiet
        pass


def _serve(handler_cls):
    """Start ``handler_cls`` on a daemon thread; return ``(base_url, shutdown)``."""
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host, port = srv.server_address
    return f"http://{host}:{port}", srv.shutdown


class TestIcsUrlFetchRefusesRedirect:
    @pytest.fixture(autouse=True)
    def _no_proxy(self, monkeypatch):
        # urllib must talk straight to 127.0.0.1, never via an ambient proxy.
        monkeypatch.setenv("no_proxy", "*")
        monkeypatch.setenv("NO_PROXY", "*")

    def test_fetch_ics_url_does_not_follow_a_302(self):
        # Revert-failing: the DEFAULT opener follows the 302 to /target (a
        # different host in the wild — cloud metadata / loopback) and returns its
        # body; the hardened no_redirect_opener raises HTTPError(302) BEFORE
        # /target is ever requested. is_local_endpoint (pre-fetch) can't catch
        # this — it only saw the original public URL.
        followed = {"hit": False}

        class Redir(_Quiet):
            def do_GET(self):
                if self.path == "/target":         # only reached if a bounce is followed
                    followed["hit"] = True
                    body = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(302)
                    self.send_header("Location", "/target")
                    self.end_headers()

        base, shutdown = _serve(Redir)
        try:
            with pytest.raises(Exception):
                ws._fetch_ics_url(base + "/start", timeout=4)
            assert followed["hit"] is False        # egress never bounced onward
        finally:
            shutdown()

    def test_load_ics_sources_skips_a_redirecting_feed(self, tmp_path, monkeypatch):
        # End to end through the caller: a public-looking https feed clears the
        # pre-fetch https + is_local_endpoint gate (a bare hostname is remote —
        # no DNS), then the server 302s. The real _fetch_ics_url raises
        # HTTPError(302), which load_ics_sources' except-continue skips, so the
        # feed contributes nothing and the redirect target is never fetched.
        monkeypatch.setenv("DREAMLAYER_DIR", str(tmp_path))
        followed = {"hit": False}

        class Redir(_Quiet):
            def do_GET(self):
                if self.path == "/target":
                    followed["hit"] = True
                    self.send_response(200)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"{}")
                else:
                    self.send_response(302)
                    self.send_header("Location", "/target")
                    self.end_headers()

        base, shutdown = _serve(Redir)
        try:
            # The config URL LOOKS public (clears the gate); the fetcher routes
            # through the REAL hardened _fetch_ics_url against the local 302 server
            # (in production these are the same host — a public feed that bounces).
            cfg = BrainConfig(network_mode="connected",
                              calendar_ics=["https://public.example/cal.ics"])
            out = ws.load_ics_sources(
                cfg, fetcher=lambda u: ws._fetch_ics_url(base + "/start", timeout=4))
            assert out == []                       # the redirecting feed is skipped
            assert followed["hit"] is False        # target never hit
        finally:
            shutdown()


# ---------------------------------------------------------------------------
# Wiring: the Brain picks the honest platform default; seams still win
# ---------------------------------------------------------------------------

class TestBrainDispatch:
    def test_windows_brain_uses_windows_sources(self, tmp_path, monkeypatch):
        import dreamlayer.ai_brain.server.server as srv
        monkeypatch.setattr(srv.platform, "system", lambda: "Windows")
        cfg = tmp_path / "cfg"; cfg.mkdir()
        brain = srv.Brain(cfg)
        assert brain._sources_fn is ws.collect_documents
        assert brain._messages_fn is ws.recent_messages
        assert brain._calendar_reader is ws.read_calendar_events

    def test_default_brain_keeps_macos_sources(self, tmp_path):
        import platform
        if platform.system() == "Windows":
            return
        from dreamlayer.ai_brain.server import Brain
        from dreamlayer.ai_brain.server import macos_sources as mac
        cfg = tmp_path / "cfg"; cfg.mkdir()
        brain = Brain(cfg)
        assert brain._sources_fn is mac.collect_documents
        assert brain._calendar_reader is mac.read_calendar_events
        assert brain._calendar_lister is mac.list_calendars

    def test_ics_events_flow_through_the_calendar_sync_seam(self, tmp_path):
        from dreamlayer.ai_brain.server import Brain
        now = time.time()
        reader = lambda config: ws.read_calendar_events(
            config, reader=lambda: [
                ("Home", _ics(_vevent("Recital", _utc(now + 3600))))])
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(calendar_sync=True).save(cfg)
        brain = Brain(cfg, calendar_reader_fn=reader)
        r = brain.sync_calendar()
        assert r["synced"] == 1
        assert any(e["title"] == "Recital" and e["source"] == "calendar"
                   for e in brain.calendar(50))

    def test_calendar_ics_survives_config_round_trip(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        c = BrainConfig(calendar_ics=["C:/cal/home.ics"])
        c.save(cfg)
        assert BrainConfig.load(cfg).calendar_ics == ["C:/cal/home.ics"]

    def test_apply_config_accepts_calendar_ics(self, tmp_path):
        from dreamlayer.ai_brain.server import Brain
        cfg = tmp_path / "cfg"; cfg.mkdir()
        brain = Brain(cfg)
        brain.apply_config({"calendar_ics": ["https://example.com/a.ics"]})
        assert BrainConfig.load(cfg).calendar_ics == ["https://example.com/a.ics"]


# ---------------------------------------------------------------------------
# Panel copy: shared page, honest words per platform
# ---------------------------------------------------------------------------

class TestPanelCopy:
    def test_macos_panel_is_byte_for_byte_unchanged(self):
        from dreamlayer.ai_brain.server.panel import render_panel, _PAGE
        assert render_panel("tok") == _PAGE.replace("__TOKEN__", "tok")
        assert render_panel("tok", os_name="Darwin") == render_panel("tok")

    def test_every_substitution_still_matches_the_page(self):
        # guard against drift: a reworded macOS string must update the table
        from dreamlayer.ai_brain.server.panel import _PAGE, _WINDOWS_COPY
        for mac_copy, _ in _WINDOWS_COPY:
            assert _PAGE.count(mac_copy) == 1, f"drifted: {mac_copy[:60]!r}"

    def test_windows_panel_tells_the_truth(self):
        from dreamlayer.ai_brain.server.panel import render_panel
        win = render_panel("tok", os_name="Windows")
        assert "Thunderbird" in win
        assert "Calendar.app" not in win
        assert "Read email &amp; iMessage" not in win
        assert "not available on Windows" in win        # contacts + reminders
        assert "never while Incognito" in win           # URL feeds stay gated
        # the Platinum design is shared — same stylesheet, same ids
        mac = render_panel("tok")
        assert win.count("<section") == mac.count("<section")
        assert 'id="email"' in win and 'id="calSync"' in win
