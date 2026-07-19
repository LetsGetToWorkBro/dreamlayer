"""test_release_audit_2026_07_19.py — regression suite for the pre-release
adversarial audit of the desktop Brain app (2026-07-19).

Every test below is *revert-failing*: undo the matching fix and the assertion
breaks. The findings, by severity:

  B1 (CRITICAL) — a zero-click stored XSS on the panel: the calendar-name
     onchange handler interpolated JSON.stringify(name) WITHOUT the esc() its
     siblings use, so an .ics feed's X-WR-CALNAME could break out of the
     attribute and steal the injected panel token. Fix: esc(JSON.stringify(c)).
  A1 (CRITICAL) — DNS rebinding: do_GET/do_POST trusted the loopback PEER IP and
     _get_root handed the token to any localhost caller, but never validated the
     Host header — so a rebound attacker page reads the token same-origin. Fix:
     a Host allowlist (IP-literal / localhost / .local / this host) → 421.
  A2 (HIGH) — arbitrary write: _write_upload joined an attacker-controlled `name`
     onto the watched folder; an absolute name or ".." ESCAPED it (pathlib drops
     the left side on an absolute join), and even a bare name could land on an
     auto-run / secret file. Fix: basename + confine-to-target + a write denylist.
  B2 (HIGH) — the token-bearing panel shipped no CSP, so an XSS could silently
     exfiltrate the token. Fix: a panel-compatible CSP (keeps inline handlers,
     pins connect-src/img-src to self so the token can't leave the origin).
  A3 (MED) — SSRF: is_local_endpoint classed 169.254.0.0/16 as "local", and the
     model endpoint was fetched from config, so a base_url at the cloud metadata
     service (169.254.169.254) was reachable. Fix: is_blocked_endpoint refuses
     link-local / IMDS at the request chokepoint and at config time.
  C1 (MED) — Windows: _harden_windows_acl SKIPPED hardening when the user SID
     couldn't be resolved, leaving secrets at the inherited (Users-readable)
     baseline. Fix: a SID-independent OWNER-RIGHTS fallback DACL (fail-closed).
  D-B3 (HIGH) — the receipt ledger's tamper-evidence had a rollback/wipe hole:
     restoring an older signed {activity.jsonl,.head} snapshot, or deleting both,
     is self-consistent and verify() passed. Fix: an external (keychain) rollback
     watermark verify() checks — a file shorter than the mark is flagged.
"""
from __future__ import annotations

import socket
import threading

import pytest

import dreamlayer.ai_brain.server.server as srv
import dreamlayer.ai_brain.server.store as store
import dreamlayer.ai_brain.server.backends as backends
from dreamlayer.ai_brain.server import Brain, BrainConfig, make_brain_server
from dreamlayer.ai_brain.server.panel import render_panel


# ---------------------------------------------------------------------------
# helpers — a real tokenless loopback Brain + a raw-socket client so we can set
# a Host header urllib would otherwise force to match the URL.
# ---------------------------------------------------------------------------

def _serve(brain):
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "127.0.0.1", server.server_address[1]


def _raw(host, port, request: bytes, timeout=5) -> bytes:
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        s.sendall(request)
        s.settimeout(timeout)
        buf = b""
        while b"\r\n\r\n" not in buf:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
        return buf
    finally:
        s.close()


def _status(resp: bytes) -> int:
    try:
        return int(resp.split(b"\r\n", 1)[0].split(b" ")[1])
    except (IndexError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# B1 — panel calendar-name XSS is esc()'d like its siblings
# ---------------------------------------------------------------------------

def test_b1_calendar_name_handler_is_escaped():
    html = render_panel("tok")
    # the vulnerable form (raw JSON.stringify in the attribute) must be gone…
    assert "toggleCal(${JSON.stringify(c)}" not in html
    # …replaced by the esc()-wrapped form every sibling handler uses.
    assert "toggleCal(${esc(JSON.stringify(c))}" in html


# ---------------------------------------------------------------------------
# A1 — DNS-rebinding Host allowlist
# ---------------------------------------------------------------------------

def test_a1_rebound_host_is_refused_and_serves_no_token(tmp_path):
    brain = Brain(tmp_path)
    brain.config.token = "s3cr3t-token-value"
    server, host, port = _serve(brain)
    try:
        # a legit loopback Host serves the panel (200) WITH the token injected
        ok = _raw(host, port,
                  f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode())
        assert _status(ok) == 200
        # a rebound attacker Host is refused BEFORE the panel handler runs (421)…
        bad = _raw(host, port,
                   b"GET / HTTP/1.1\r\nHost: evil.example.com\r\nConnection: close\r\n\r\n")
        assert _status(bad) == 421
        # …and the token never appears in the refused response.
        assert b"s3cr3t-token-value" not in bad
        # a mutating POST from a rebound Host is refused too.
        badp = _raw(host, port,
                    b"POST /dreamlayer/config HTTP/1.1\r\nHost: evil.example.com\r\n"
                    b"Content-Length: 2\r\nConnection: close\r\n\r\n{}")
        assert _status(badp) == 421
    finally:
        server.shutdown()


def test_a1_ip_literal_and_mdns_and_localhost_hosts_are_allowed(tmp_path):
    server, host, port = _serve(Brain(tmp_path))
    try:
        for hdr in (f"127.0.0.1:{port}", f"localhost:{port}", "mybrain.local",
                    "192.168.1.50", f"[::1]:{port}"):
            resp = _raw(host, port,
                        f"GET / HTTP/1.1\r\nHost: {hdr}\r\nConnection: close\r\n\r\n".encode())
            assert _status(resp) == 200, f"Host {hdr!r} should be allowed"
        # a native/CLI caller with NO Host header (HTTP/1.0) is not a rebind vector
        noh = _raw(host, port, b"GET / HTTP/1.0\r\nConnection: close\r\n\r\n")
        assert _status(noh) == 200
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# B2 — the panel/builder ship a token-protecting CSP
# ---------------------------------------------------------------------------

def test_b2_panel_sends_a_token_protecting_csp(tmp_path):
    server, host, port = _serve(Brain(tmp_path))
    try:
        resp = _raw(host, port,
                    f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode())
        low = resp.lower()
        assert b"content-security-policy:" in low
        # connect-src/img-src pinned to self → an XSS can't fetch/beacon the token off-origin
        assert b"connect-src 'self'" in resp
        assert b"default-src 'self'" in resp
        assert b"object-src 'none'" in resp
    finally:
        server.shutdown()


def test_b2_csp_constant_shape():
    csp = srv.PANEL_CSP
    assert "default-src 'self'" in csp
    assert "connect-src 'self' https://api.dreamlayer.app" in csp   # the one real off-origin
    assert "frame-ancestors 'none'" in csp
    assert "'unsafe-inline'" in csp    # the panel's inline handlers still work


# ---------------------------------------------------------------------------
# A2 — _write_upload cannot escape the watched folder or write auto-run/secret
# ---------------------------------------------------------------------------

def _brain_with_watched(tmp_path):
    watched = tmp_path / "drop"; watched.mkdir()
    brain = Brain(tmp_path)
    assert brain.config.add_folder(str(watched))
    return brain, str(watched)


def test_a2_absolute_name_cannot_escape_the_watched_folder(tmp_path):
    brain, watched = _brain_with_watched(tmp_path)
    sentinel = tmp_path / "OUTSIDE.txt"
    # an ABSOLUTE name would, unfixed, drop the watched folder and write anywhere
    assert srv._write_upload(brain, watched, str(sentinel), b"pwned") is False
    assert not sentinel.exists()


def test_a2_dotdot_traversal_cannot_escape(tmp_path):
    brain, watched = _brain_with_watched(tmp_path)
    assert srv._write_upload(brain, watched, "../../ESCAPED.txt", b"pwned") is False
    assert not (tmp_path.parent / "ESCAPED.txt").exists()
    assert not (tmp_path / "ESCAPED.txt").exists()


def test_a2_benign_upload_still_works(tmp_path):
    brain, watched = _brain_with_watched(tmp_path)
    assert srv._write_upload(brain, watched, "notes.txt", b"hello") is True
    from pathlib import Path
    assert (Path(watched) / "notes.txt").read_bytes() == b"hello"


def test_a2_autorun_destination_is_denied_even_inside_a_watched_folder(tmp_path):
    # If a watched folder itself is an auto-run location, a benign basename still
    # must not materialize a runnable artifact.
    from pathlib import Path
    la = Path.home() / "Library" / "LaunchAgents"
    import types
    brain = types.SimpleNamespace(config=types.SimpleNamespace(folders=[str(la)]))
    assert srv._write_upload(brain, str(la), "evil.plist", b"<plist/>") is False


def test_a2_add_folder_refuses_autorun_and_secret_dirs():
    from pathlib import Path
    c = BrainConfig()
    for rel in ("Library/LaunchAgents", ".config/autostart", ".ssh"):
        p = str(Path.home() / rel)
        assert c.add_folder(p) is False
        assert p not in c.folders


def test_a2_is_write_denied_matrix():
    from pathlib import Path
    h = Path.home()
    for rel in ("Library/LaunchAgents/x.plist", ".config/autostart/e.desktop",
                ".bashrc", ".zshrc", ".ssh/authorized_keys", ".gnupg/secring"):
        assert store._is_write_denied(str(h / rel)) is True, rel
    for rel in ("Documents/note.txt", "Pictures/cat.png", "code/main.py"):
        assert store._is_write_denied(str(h / rel)) is False, rel


# ---------------------------------------------------------------------------
# A3 — link-local / cloud-metadata endpoints are refused (SSRF)
# ---------------------------------------------------------------------------

def test_a3_is_blocked_endpoint_matrix():
    for url in ("http://169.254.169.254/latest/meta-data/",
                "http://169.254.169.254", "https://[fd00:ec2::254]/",
                "http://169.254.1.2:8080/v1"):
        assert backends.is_blocked_endpoint(url) is True, url
    for url in ("http://127.0.0.1:11434", "http://192.168.1.5:1234/v1",
                "https://api.openai.com/v1", ""):
        assert backends.is_blocked_endpoint(url) is False, url


def test_a3_provider_chat_refuses_a_metadata_endpoint():
    # even with an injectable double, a metadata base_url is refused before use
    called = {"n": 0}
    def spy(url, payload):
        called["n"] += 1
        return {"text": "leaked-credentials"}
    with pytest.raises(ValueError):
        backends._provider_chat("custom", "http://169.254.169.254/", "m", "", "hi",
                                http_post=spy)
    assert called["n"] == 0     # the double was never reached


def test_a3_apply_config_rejects_a_metadata_endpoint(tmp_path):
    brain = Brain(tmp_path)
    brain.apply_config({"api_base_url": "http://127.0.0.1:1234/v1"})
    assert brain.config.api_base_url == "http://127.0.0.1:1234/v1"
    # a patch pointing at IMDS is rejected — the prior value is kept
    brain.apply_config({"api_base_url": "http://169.254.169.254/v1"})
    assert brain.config.api_base_url == "http://127.0.0.1:1234/v1"


# ---------------------------------------------------------------------------
# C1 — SID-independent owner-only DACL fallback (fail-closed, not fail-open)
# ---------------------------------------------------------------------------

def test_c1_sidless_argv_is_owner_only_and_sid_independent():
    argv = store._owner_only_icacls_argv_sidless("C:\\state\\brain_config.json")
    assert argv[0] == "icacls"
    assert "/inheritance:r" in argv            # strips inherited Users/Everyone
    grants = " ".join(argv)
    assert "*S-1-3-4:F" in grants              # OWNER RIGHTS — owner keeps access
    assert "*S-1-5-18:F" in grants and "*S-1-5-32-544:F" in grants  # SYSTEM + Admins
    # no broad principal is granted (no Users/Everyone/Authenticated Users)
    for broad in ("S-1-1-0", "S-1-5-32-545", "S-1-5-11", ":(OI)(CI)F Everyone"):
        assert broad not in grants


def test_c1_resolved_sid_path_still_uses_the_specific_user_sid():
    # the common path is unchanged: a resolvable SID → the user-SID grant, and a
    # MISSING sid still returns None from the strict builder (the caller falls back)
    assert store._owner_only_icacls_argv("C:\\x", "S-1-5-21-1-2-3-1001") is not None
    assert store._owner_only_icacls_argv("C:\\x", None) is None


# ---------------------------------------------------------------------------
# D-B3 — receipt ledger rollback / wipe detection via the external watermark
# ---------------------------------------------------------------------------

class _MemStore:
    """An in-memory stand-in for the keychain-backed SecretStore, so the
    watermark is exercised hermetically (no real keychain touched)."""
    def __init__(self):
        self.d = {}
    def get(self, k):
        return self.d.get(k)
    def set(self, k, v):
        self.d[k] = v


def _signer():
    try:
        from dreamlayer.reality_compiler.sign_crypto import Signer
    except Exception:
        return None
    if not getattr(Signer, "available", False):
        return None
    return Signer(b"\x02" * 32)


requires_crypto = pytest.mark.skipif(_signer() is None,
                                     reason="Ed25519 signer (cryptography) unavailable")


@requires_crypto
def test_db3_clean_ledger_verifies_and_sets_the_watermark(tmp_path):
    wm = store._ReceiptWatermark(_MemStore())
    log = store.ActivityLog(tmp_path, signer=_signer(), watermark=wm)
    for i in range(5):
        log.add("t", f"event {i}")
    v = log.verify()
    assert v["ok"] is True and v["records"] == 5
    assert wm.get(_signer().public_key_hex) == 5
    assert not v.get("rolled_back")


@requires_crypto
def test_db3_full_wipe_is_flagged_not_a_clean_empty_ledger(tmp_path):
    mem = _MemStore()
    log = store.ActivityLog(tmp_path, signer=_signer(),
                            watermark=store._ReceiptWatermark(mem))
    for i in range(4):
        log.add("t", f"event {i}")
    # attacker deletes BOTH the ledger and its signed anchor
    log.path.unlink()
    if log._head_path.exists():
        log._head_path.unlink()
    log2 = store.ActivityLog(tmp_path, signer=_signer(),
                             watermark=store._ReceiptWatermark(mem))
    v = log2.verify()
    assert v["ok"] is False
    assert v.get("rolled_back") is True     # a wipe is NOT reported as ok/empty


@requires_crypto
def test_db3_snapshot_rollback_is_flagged(tmp_path):
    mem = _MemStore()
    log = store.ActivityLog(tmp_path, signer=_signer(),
                            watermark=store._ReceiptWatermark(mem))
    log.add("t", "a"); log.add("t", "b")
    snap_a = log.path.read_bytes()
    snap_h = log._head_path.read_bytes()      # an older, validly-signed pair
    log.add("t", "c"); log.add("t", "d"); log.add("t", "e")
    import json as _json
    assert _json.loads(mem.d["receipt_hw"].decode())["count"] == 5
    # restore the 2-record snapshot — self-consistent with its own anchor
    log.path.write_bytes(snap_a)
    log._head_path.write_bytes(snap_h)
    log2 = store.ActivityLog(tmp_path, signer=_signer(),
                             watermark=store._ReceiptWatermark(mem))
    v = log2.verify()
    assert v["signed"] == 2
    assert v["ok"] is False and v.get("rolled_back") is True


@requires_crypto
def test_db3_legit_prune_lowers_the_watermark_no_false_positive(tmp_path):
    mem = _MemStore()
    wm = store._ReceiptWatermark(mem)
    log = store.ActivityLog(tmp_path, signer=_signer(), watermark=wm)
    for i in range(5):
        log.add("t", f"event {i}")
    # an OWNER prune re-chains the survivors AND re-attests the head → the mark
    # follows down, so verify() stays clean (the attacker path, which never runs
    # _write_head, is the one left stale).
    survivors = list(reversed(log.recent(40)))[:2]
    log._rechain(survivors)
    v = log.verify()
    assert v["ok"] is True
    assert v.get("rolled_back") in (None, False)
    assert wm.get(_signer().public_key_hex) == 2


@requires_crypto
def test_db3_reinstall_with_a_new_key_ignores_the_stale_watermark(tmp_path):
    # The keychain mark OUTLIVES the state dir by design (that's what defeats a
    # state-dir rollback). A legit reinstall mints a NEW seed and starts an EMPTY
    # ledger, so a stale mark from the OLD key must NOT read as a rollback — the
    # key change is the CLIENT's signal (key-pin), not a server false alarm.
    from dreamlayer.reality_compiler.sign_crypto import Signer
    mem = _MemStore()
    old = store.ActivityLog(tmp_path / "a", signer=Signer(b"\x02" * 32),
                            watermark=store._ReceiptWatermark(mem))
    for i in range(5):
        old.add("t", f"e{i}")
    # a DIFFERENT device key reading the same shared keychain mark
    new = store.ActivityLog(tmp_path / "b", signer=Signer(b"\x09" * 32),
                            watermark=store._ReceiptWatermark(mem))
    v = new.verify()
    assert v["records"] == 0
    assert v.get("rolled_back") in (None, False)   # stale mark under the old key ⇒ ignored


@requires_crypto
def test_db3_no_watermark_preserves_prior_behavior(tmp_path):
    # with no watermark wired (watermark=None), verify() behaves exactly as before
    log = store.ActivityLog(tmp_path, signer=_signer())   # watermark defaults None
    for i in range(3):
        log.add("t", f"e{i}")
    v = log.verify()
    assert v["ok"] is True and "rolled_back" not in v
