"""Live Lens — a phone browser becomes the glasses (ai_brain/server/live.py).

The load-bearing claims, each pinned here:
  * the HUD budget is the REAL canonical unit (MAX_LINES x MAX_TEXT_LEN utf-8
    bytes from reality_compiler.v2.figment), enforced on every card;
  * a look is ONE unified pipeline (live.world_look) shared with the phone
    app's /brain/look: the full World lens + plugin providers outside the
    wearer's egress shield, an honest LOCAL-ONLY classifier look (zero egress,
    no trace) inside it — and the decoded frame never touches disk;
  * the page is public but inert (never embeds the token — the credential
    rides the link's URL fragment, handed out local-only like pairing);
  * the look route sits behind the same token gate + 413-before-read body cap
    as the rest of the surface;
  * --tls machinery mints a reusable appliance cert so a phone browser gets
    the secure context its camera requires.
"""
from __future__ import annotations

import io
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import dreamlayer.ai_brain.server.live as live
from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.live import (
    MAX_FRAME_BYTES, decode_frame, look, render_live, wrap_hud_lines,
)
from dreamlayer.ai_brain.server.store import BrainConfig
from dreamlayer.reality_compiler.v2.figment import MAX_LINES, MAX_TEXT_LEN

TOKEN = "rune-birch"


def _brain(tmp_path, **cfg) -> Brain:
    d = tmp_path / "cfg"
    d.mkdir()
    BrainConfig(token=TOKEN, **cfg).save(d)
    return Brain(d)


def _jpeg(size=(64, 64), color=(30, 200, 90)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


# --- the HUD budget: the canonical unit, enforced ---------------------------

class TestWrapHudLines:
    def test_ascii_fits_and_wraps(self):
        lines = wrap_hud_lines("the passport is in the top drawer of the desk")
        assert 1 <= len(lines) <= MAX_LINES
        for ln in lines:
            assert len(ln.encode("utf-8")) <= MAX_TEXT_LEN

    def test_multibyte_counts_bytes_not_chars(self):
        # the unit is UTF-8 BYTES (the glass's 24-byte slot buffers): CJK gets
        # 8 chars per line, not 24 — the parity rule all interpreters share.
        lines = wrap_hud_lines("記憶は自分のものだから守る価値がある")
        for ln in lines:
            assert len(ln.encode("utf-8")) <= MAX_TEXT_LEN

    def test_over_budget_word_is_split_not_dropped(self):
        lines = wrap_hud_lines("a" * 60)
        assert lines[0] == "a" * MAX_TEXT_LEN
        assert "".join(lines).rstrip("…").count("a") == 60

    def test_overflow_truncates_to_max_lines_with_marker(self):
        lines = wrap_hud_lines("word " * 60)
        assert len(lines) == MAX_LINES
        assert lines[-1].endswith("…")
        for ln in lines:
            assert len(ln.encode("utf-8")) <= MAX_TEXT_LEN

    def test_empty_is_empty(self):
        assert wrap_hud_lines("") == []


# --- frame decode: in memory, bounded, never trusting the bytes -------------

class TestDecodeFrame:
    def test_jpeg_roundtrip(self):
        pytest.importorskip("PIL")
        arr = decode_frame(_jpeg())
        assert arr is not None and arr.shape == (64, 64, 3)

    def test_garbage_is_none_not_a_crash(self):
        assert decode_frame(b"") is None
        assert decode_frame(b"not an image at all") is None

    def test_large_frame_is_downscaled(self):
        pytest.importorskip("PIL")
        arr = decode_frame(_jpeg(size=(1600, 1200)))
        assert arr is not None and max(arr.shape[:2]) <= 512


# --- look(): the local ladder, the ledger, and the no-egress guarantee ------

class TestLook:
    def test_hit_becomes_a_budget_card_and_ledger_entry(self, tmp_path, monkeypatch):
        pytest.importorskip("PIL")
        brain = _brain(tmp_path)
        monkeypatch.setattr(live, "_ladder", lambda arr: ("houseplant", 0.87))
        out = look(brain, _jpeg())
        assert out["ok"] is True and out["label"] == "houseplant"
        assert out["tier"] == "laptop"                    # on-device class
        for ln in out["lines"]:
            assert len(ln.encode("utf-8")) <= MAX_TEXT_LEN
        assert len(out["lines"]) <= MAX_LINES
        assert any(i["kind"] == "look" for i in brain.activity.recent())

    def test_no_recognition_is_honest_not_invented(self, tmp_path, monkeypatch):
        pytest.importorskip("PIL")
        brain = _brain(tmp_path)
        monkeypatch.setattr(live, "_ladder", lambda arr: None)
        out = look(brain, _jpeg())
        assert out["ok"] is True and out["label"] == ""
        assert out["confidence"] == 0.0

    def test_backend_crash_degrades_to_no_recognition(self, tmp_path, monkeypatch):
        pytest.importorskip("PIL")
        brain = _brain(tmp_path)
        def boom(arr):
            raise RuntimeError("backend died mid-frame")
        monkeypatch.setattr(live, "_ladder", boom)
        out = look(brain, _jpeg())
        assert out["ok"] is True and out["label"] == ""   # graceful, never a 500

    def test_undecodable_frame_reports_reason(self, tmp_path):
        brain = _brain(tmp_path)
        out = look(brain, b"junk")
        assert out["ok"] is False and "decode" in out["reason"]

    def test_look_never_egresses_and_never_writes_the_frame(self, tmp_path, monkeypatch):
        # The privacy claim, both halves. Egress: cloud_calls stays 0 even with
        # a cloud provider fully configured. Residue: no new non-state file
        # appears anywhere under the brain dir (state = the json/db files the
        # activity ledger and config legitimately touch).
        pytest.importorskip("PIL")
        brain = _brain(tmp_path, cloud_provider="openai",
                       cloud_api_key="sk-x", cloud_model="gpt-4o-mini")
        monkeypatch.setattr(live, "_ladder", lambda arr: ("mug", 0.9))
        allowed = {".json", ".jsonl", ".db", ".db-journal", ".db-wal", ".db-shm",
                   ".head", ".key"}   # receipt anchor + signing seed are state
        before = {p for p in Path(tmp_path).rglob("*")
                  if p.is_file() and p.suffix not in allowed}
        out = look(brain, _jpeg())
        assert out["ok"] is True
        assert brain.config.cloud_calls == 0              # zero egress, always
        after = {p for p in Path(tmp_path).rglob("*")
                 if p.is_file() and p.suffix not in allowed}
        assert after == before                            # no frame residue

    def test_look_leaves_no_ledger_trace_while_incognito(self, tmp_path, monkeypatch):
        # The one thing a look persists is the "saw X" observation in the activity
        # ledger. When the wearer has signalled privacy (incognito / lan_only),
        # that on-disk trace is suppressed — the look still WORKS on-device, it
        # just leaves nothing behind (refute 2026-07-18: recorded in every posture).
        pytest.importorskip("PIL")
        brain = _brain(tmp_path, network_mode="lan_only")   # incognito_now() → True
        assert brain.incognito_now() is True
        monkeypatch.setattr(live, "_ladder", lambda arr: ("houseplant", 0.87))
        out = look(brain, _jpeg())
        assert out["ok"] is True and out["label"] == "houseplant"   # look still works
        # REVERT-FAILING: no durable record of what the camera saw while veiled
        assert not any(i["kind"] == "look" for i in brain.activity.recent())

    def test_look_never_identifies_a_person_on_the_hud(self, tmp_path, monkeypatch):
        # The Live Lens renders the classifier label DIRECTLY — it never passes
        # through the object-lens person defence — so it must apply the same
        # "never identify a stranger" guard itself. Otherwise a YOLO "person"
        # (COCO class 0) or a VLM-read NAME walks onto the HUD and into the ledger
        # (refute 2026-07-18, a sibling call-site the object-lens guard never
        # reached). Deferral must happen BEFORE the ledger write, too.
        pytest.importorskip("PIL")
        brain = _brain(tmp_path)
        # (a) the classifier returns the COCO "person" class → not on the glass,
        #     and nothing recorded in the activity ledger.
        monkeypatch.setattr(live, "_ladder", lambda arr: ("person", 0.95))
        out = look(brain, _jpeg())
        assert out["ok"] is True and out["label"] == ""
        assert not any(i["kind"] == "look" for i in brain.activity.recent())
        # (b) an ALL-CAPS name read off a nametag defers too — exercises BOTH the
        #     case-insensitive name shape AND the Live Lens wiring (REVERT-FAILING).
        monkeypatch.setattr(live, "_ladder", lambda arr: ("MAYA CHEN", 0.96))
        assert look(brain, _jpeg())["label"] == ""
        # (c) a real OBJECT still renders normally — the guard only defers people.
        monkeypatch.setattr(live, "_ladder", lambda arr: ("houseplant", 0.88))
        assert look(brain, _jpeg())["label"] == "houseplant"


# --- the page: public but inert ---------------------------------------------

class TestPage:
    def test_page_has_the_working_parts(self):
        html = render_live()
        assert "getUserMedia" in html                     # camera
        assert "/dreamlayer/live/look" in html            # look wire
        assert "/dreamlayer/brain/ask" in html            # the PRODUCTION ask
        assert "veil" in html                             # the wearer's posture
        assert "isSecureContext" in html                  # honest camera gate
        assert f'"maxTextLen": {MAX_TEXT_LEN}' in html \
            or f'"maxTextLen":{MAX_TEXT_LEN}' in html     # real budget injected

    def test_page_never_embeds_a_token(self, tmp_path):
        # the credential rides the URL fragment of the panel's link — the HTML
        # itself must be inert no matter who fetches it.
        assert TOKEN not in render_live()

    def test_hud_renders_as_text_not_html(self):
        # The classifier label + ask answer (arbitrary model/memory output) reach
        # the HUD via textContent — as TEXT. A textContent->innerHTML regression
        # would be token-stealing XSS (the token lives in sessionStorage). Pin it.
        page = render_live()
        assert "hud.textContent" in page
        assert "hud.innerHTML" not in page

    def test_nonce_stamps_the_inline_script_and_style(self):
        # with a nonce, the sole inline <script>/<style> carry it (so a strict
        # CSP can allow them while blocking injected script); without, bare tags.
        page = render_live("abc123")
        assert '<script nonce="abc123">' in page
        assert '<style nonce="abc123">' in page
        bare = render_live()
        assert "<script>" in bare and "nonce=" not in bare


# --- the HTTP surface: gate, caps, link ------------------------------------

def _serve(brain):
    server = make_brain_server(brain, "127.0.0.1", 0, tls_port=7877)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _req(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class TestHttpSurface:
    def test_page_is_public_and_inert_look_is_gated(self, tmp_path, monkeypatch):
        pytest.importorskip("PIL")
        brain = _brain(tmp_path)
        monkeypatch.setattr(live, "_ladder", lambda arr: ("book", 0.8))
        server, base = _serve(brain)
        try:
            status, body = _req(base + "/dreamlayer/live")
            assert status == 200
            page = body.decode("utf-8")
            assert "getUserMedia" in page and TOKEN not in page
            # no token → 401 before anything is looked at
            status, _ = _req(base + "/dreamlayer/live/look", data=_jpeg())
            assert status == 401
            # token → a real card from the (injected) ladder
            status, body = _req(base + "/dreamlayer/live/look", data=_jpeg(),
                                headers={"X-DreamLayer-Token": TOKEN})
            assert status == 200
            out = json.loads(body)
            assert out["ok"] is True and out["label"] == "book"
        finally:
            server.shutdown(); server.server_close()

    def test_live_page_carries_a_strict_nonce_csp(self, tmp_path):
        # Defence-in-depth: the served page must carry a CSP whose script-src is
        # nonce-based (NOT 'unsafe-inline'), and the nonce must match the page's
        # inline <script>/<style> — so injected <script>/<img onerror> can't run.
        import re
        brain = _brain(tmp_path)
        server, base = _serve(brain)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(base + "/dreamlayer/live", timeout=10) as r:
                csp = r.headers.get("Content-Security-Policy")
                page = r.read().decode("utf-8")
            assert csp, "no Content-Security-Policy header"
            script_dir = next(p for p in csp.split(";") if "script-src" in p)
            assert "'nonce-" in script_dir and "'unsafe-inline'" not in script_dir
            nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)
            assert f'<script nonce="{nonce}">' in page      # header nonce == tag nonce
            assert f'<style nonce="{nonce}">' in page
        finally:
            server.shutdown(); server.server_close()

    def test_oversize_frame_is_413_before_read(self, tmp_path):
        # The refusal happens on the DECLARED length, before any body byte is
        # read (the hardening contract) — so speak raw HTTP: send only the
        # headers claiming an oversize body and read the early 413. urllib
        # can't test this; it breaks its own pipe mid-upload when the server
        # (correctly) refuses without draining.
        import socket
        brain = _brain(tmp_path)
        server, base = _serve(brain)
        host, port = "127.0.0.1", server.server_address[1]
        try:
            req = (f"POST /dreamlayer/live/look HTTP/1.1\r\n"
                   f"Host: {host}:{port}\r\n"
                   f"X-DreamLayer-Token: {TOKEN}\r\n"
                   f"Content-Length: {MAX_FRAME_BYTES + 1}\r\n"
                   f"\r\n").encode()
            with socket.create_connection((host, port), timeout=10) as s:
                s.sendall(req)                 # headers only — no body follows
                s.settimeout(10)
                buf = b""
                while b"\r\n\r\n" not in buf:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            assert b" 413 " in buf.split(b"\r\n", 1)[0]
        finally:
            server.shutdown(); server.server_close()

    def test_link_is_local_only_carries_fragment_and_advertises_tls(self, tmp_path):
        brain = _brain(tmp_path)
        server, base = _serve(brain)                      # tls_port=7877 above
        try:
            status, body = _req(base + "/dreamlayer/live/link",
                                headers={"X-DreamLayer-Token": TOKEN})
            assert status == 200
            out = json.loads(body)
            assert out["url"].startswith("https://")      # the camera-able link
            assert "#t=" + TOKEN in out["url"]            # fragment credential
            assert out["https"] is True
            assert out["qr"].lstrip().startswith("<svg")
        finally:
            server.shutdown(); server.server_close()

    def test_ask_honors_the_veil_with_cloud_configured(self, tmp_path):
        # the Live Lens sends no_cloud with every veiled ask; even a fully
        # cloud-wired Brain must not egress — the production /brain/ask
        # contract, pinned from the page's exact call shape.
        brain = _brain(tmp_path, cloud_provider="openai",
                       cloud_api_key="sk-x", cloud_model="gpt-4o-mini")
        server, base = _serve(brain)
        try:
            status, body = _req(
                base + "/dreamlayer/brain/ask",
                data=json.dumps({"query": "what is my lease", "no_cloud": True}
                                ).encode(),
                headers={"X-DreamLayer-Token": TOKEN,
                         "Content-Type": "application/json"})
            assert status == 200
            assert brain.config.cloud_calls == 0
        finally:
            server.shutdown(); server.server_close()


# --- tls.py: the appliance certificate --------------------------------------

class TestTls:
    def test_mints_reuses_and_loads(self, tmp_path):
        pytest.importorskip("cryptography")
        from dreamlayer.ai_brain.server.tls import (
            ensure_self_signed, make_ssl_context,
        )
        pair = ensure_self_signed(tmp_path)
        assert pair is not None
        cert_p, key_p = pair
        assert cert_p.exists() and key_p.exists()
        assert (key_p.stat().st_mode & 0o777) == 0o600    # private stays private
        first = cert_p.read_bytes()
        again = ensure_self_signed(tmp_path)              # second call: reuse
        assert again is not None and again[0].read_bytes() == first
        ctx = make_ssl_context(cert_p, key_p)             # loadable = valid pair
        assert ctx is not None

    def test_cert_names_loopback(self, tmp_path):
        pytest.importorskip("cryptography")
        from cryptography import x509
        from dreamlayer.ai_brain.server.tls import ensure_self_signed
        cert_p, _ = ensure_self_signed(tmp_path)
        cert = x509.load_pem_x509_certificate(cert_p.read_bytes())
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        ips = {str(i) for i in ext.value.get_values_for_type(x509.IPAddress)}
        assert "127.0.0.1" in ips

    def test_key_and_dir_get_the_owner_only_acl(self, tmp_path, monkeypatch):
        # The TLS private key is a secret-at-rest: 0o600 is INERT on NTFS, so the
        # key (and its dir) must get the owner-only Windows ACL, exactly like
        # brain_config. Cross-platform: record the ACL calls the mint makes.
        pytest.importorskip("cryptography")
        from dreamlayer.ai_brain.server import store, tls
        hardened: list = []
        monkeypatch.setattr(store, "_harden_windows_acl", lambda p: hardened.append(p))
        cert_p, key_p = tls.ensure_self_signed(tmp_path)
        # REVERT-FAILING: both the tls dir AND the private key are hardened
        assert str(key_p.parent) in hardened      # the tls/ dir (children inherit)
        assert str(key_p) in hardened             # the private key file itself
        # reuse re-tightens too — a key restored with a wide ACL is fixed on start
        hardened.clear()
        tls.ensure_self_signed(tmp_path)          # second call reuses the cert
        assert str(key_p) in hardened

    def test_mismatched_key_is_reminted_not_crashed(self, tmp_path):
        # A key that doesn't match the cert (e.g. a crash between the two writes)
        # must re-mint HERE, not surface as an uncaught SSLError at wrap_socket
        # that takes the whole Brain down. Reverted, ensure_self_signed returns
        # the bad pair and make_ssl_context raises.
        pytest.importorskip("cryptography")
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from dreamlayer.ai_brain.server.tls import ensure_self_signed, make_ssl_context
        cert_p, key_p = ensure_self_signed(tmp_path)
        good_cert = cert_p.read_bytes()
        # overwrite the key with an UNRELATED (valid PEM, wrong) key → mismatch
        key_p.write_bytes(ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        cert_p2, key_p2 = ensure_self_signed(tmp_path)     # must detect + re-mint
        assert cert_p2.read_bytes() != good_cert           # a fresh, matched pair
        assert make_ssl_context(cert_p2, key_p2) is not None   # loads, no SSLError


# --- One Lens: the browser tap and the app shutter are one pipeline ---------

class TestOneLens:
    """live.world_look — the single look behind /dreamlayer/live/look AND
    /dreamlayer/brain/look, so the two surfaces are literally one thing."""

    PRICE = ('{"label":"price tag","confidence":0.9,'
             '"attributes":{"amount":20,"currency":"EUR"}}')

    def _world_brain(self, tmp_path, describe_reply, **cfg):
        """A real Brain whose vision backend + one plugin provider are stubbed
        at the same seams the product uses (backend.describe / the object-lens
        provider registry)."""
        from dreamlayer.plugins.currency import CurrencyProvider
        brain = _brain(tmp_path, **cfg)

        class _B:
            def describe(self, prompt, image_b64):
                return describe_reply
            def vision(self, label, image_b64, want):
                return ""
        brain._backend = _B()
        wl = brain.world_lens()
        assert wl is not None
        wl.object_lens.registry.register(
            CurrencyProvider(home="USD", rates_fetch=lambda a, b: 1.10))
        return brain

    def test_browser_look_returns_plugin_rows_on_the_glass(self, tmp_path):
        pytest.importorskip("PIL")
        brain = self._world_brain(tmp_path, self.PRICE)
        out = look(brain, _jpeg())
        assert out["ok"] is True and out["label"] == "price tag"
        # the Currency connector's row made it onto the glass lines
        assert any("$22.00" in ln for ln in out["lines"])
        assert "currency" in out["sources"]
        # and into the panel richer surfaces render
        assert any("$22.00" in r["label"] for r in out["panel"]["rows"])
        # every line honors the canonical budget
        assert len(out["lines"]) <= MAX_LINES
        assert all(len(ln.encode("utf-8")) <= MAX_TEXT_LEN for ln in out["lines"])
        # the look is on the ledger (shield is down)
        assert any(i["kind"] == "look" for i in brain.activity.recent())

    def test_shield_up_look_is_local_only(self, tmp_path, monkeypatch):
        pytest.importorskip("PIL")
        # lan_only raises the egress shield: the World lens must not even be
        # consulted — the classifier answers, nothing egresses, nothing is
        # written, and the response says local_only.
        brain = self._world_brain(tmp_path, self.PRICE, network_mode="lan_only")
        assert brain.incognito_now() is True
        def _boom():
            raise AssertionError("world lens consulted under the shield")
        monkeypatch.setattr(brain, "world_lens", _boom)
        monkeypatch.setattr(live, "_ladder", lambda arr: ("mug", 0.9))
        out = look(brain, _jpeg())
        assert out["ok"] is True and out["label"] == "mug"
        assert out["local_only"] is True
        assert out["panel"]["rows"] == []               # shape parity, no providers
        assert brain.config.cloud_calls == 0
        assert not any(i["kind"] == "look" for i in brain.activity.recent())

    def test_both_routes_share_one_formatter(self, tmp_path):
        pytest.importorskip("PIL")
        # The browser route (JPEG body) and the app route (base64 JSON) must
        # return the SAME glass lines for the same photo — one pipeline.
        import base64 as b64mod
        brain = self._world_brain(tmp_path, self.PRICE)
        server, base = _serve(brain)
        try:
            frame = _jpeg()
            hdr = {"X-DreamLayer-Token": TOKEN}
            status, body = _req(base + "/dreamlayer/live/look", data=frame,
                                headers=hdr)
            assert status == 200
            browser = json.loads(body)
            status, body = _req(
                base + "/dreamlayer/brain/look",
                data=json.dumps(
                    {"image": b64mod.b64encode(frame).decode()}).encode(),
                headers={**hdr, "Content-Type": "application/json"})
            assert status == 200
            app = json.loads(body)
            assert browser["ok"] and app["ok"]
            assert browser["label"] == app["label"] == "price tag"
            assert browser["lines"] == app["lines"]      # literally the same glass
            assert app["lens"] == "object"
        finally:
            server.shutdown(); server.server_close()

    def test_panel_lines_budget_and_layout(self):
        card = {"primary": "price tag",
                "rows": [{"label": "$22.00", "detail": "€20.00 · 1 EUR = 1.100 USD"},
                         {"label": "seen before", "detail": "3× · last at home"},
                         {"label": "x" * 60},
                         {"label": "overflow row"}],
                "footer": "90% · currency, memory"}
        lines = live.panel_lines(card)
        assert lines[0] == "price tag"
        assert len(lines) <= MAX_LINES
        assert all(len(ln.encode("utf-8")) <= MAX_TEXT_LEN for ln in lines)
        assert any(ln.startswith("$22.00") for ln in lines)
        assert lines[-1].startswith("90%")               # provenance survives

    def test_describe_remote_endpoint_is_gated_and_counted(self, tmp_path):
        # The recognizer's describe path ships the frame to ollama_url; a
        # REMOTE url is egress — blocked under the shield, counted otherwise
        # (the same contract the audit pinned for the AI explainer).
        from dreamlayer.ai_brain.server.world_lens import WorldLensHost
        calls = []

        class _B:
            def describe(self, prompt, image_b64):
                calls.append(1)
                return ""
        brain = _brain(tmp_path, ollama_url="http://203.0.113.9:11434")
        brain._backend = _B()
        wl = WorldLensHost(brain)
        wl._describe("p", "img")                          # shield down → allowed
        assert calls and brain.config.cloud_calls == 1    # …but on the ledger
        brain.config.network_mode = "lan_only"            # shield up
        calls.clear()
        assert wl._describe("p", "img") == ""             # blocked
        assert not calls and brain.config.cloud_calls == 1
