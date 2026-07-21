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

    def test_oversized_canvas_is_refused_before_it_decodes(self, monkeypatch):
        # REVERT-FAILING (SEC1, refute 2026-07-20): decode_frame must reject a
        # frame whose declared pixel count exceeds MAX_FRAME_PIXELS from the
        # HEADER, before thumbnail() forces a full-resolution decode. Shrink the
        # cap so a real 64x64 frame trips it — pre-fix (no cap) it decoded anyway,
        # which is exactly how a small PNG declaring 13000x13000 ballooned to
        # ~650 MB of RSS on the public look route.
        pytest.importorskip("PIL")
        monkeypatch.setattr(live, "MAX_FRAME_PIXELS", 100)      # 64*64 = 4096 > 100
        assert decode_frame(_jpeg(size=(64, 64))) is None
        monkeypatch.setattr(live, "MAX_FRAME_PIXELS", 50 * 1024 * 1024)
        assert decode_frame(_jpeg(size=(64, 64))) is not None   # under the cap: fine

    def test_header_declared_bomb_never_materialises_pixels(self):
        # A crafted PNG whose IHDR declares a 20000x20000 canvas (400 MP) with a
        # trivial IDAT: Image.open reads the size from the header WITHOUT decoding
        # IDAT, so the cap refuses it before a single pixel is allocated.
        pytest.importorskip("PIL")
        import struct
        import zlib

        def _chunk(typ, data):
            body = typ + data
            return (struct.pack(">I", len(data)) + body
                    + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))
        png = (b"\x89PNG\r\n\x1a\n"
               + _chunk(b"IHDR", struct.pack(">IIBBBBB", 20000, 20000, 8, 2, 0, 0, 0))
               + _chunk(b"IDAT", zlib.compress(b"\x00"))
               + _chunk(b"IEND", b""))
        assert decode_frame(png) is None      # refused at the header, no OOM

    def test_decode_is_concurrency_bounded(self):
        # SEC2: a fixed peak-memory backstop exists so a burst of authed looks
        # can't stack their decode buffers into an OOM. Prove the semaphore
        # actually gates at _MAX_CONCURRENT_DECODES: acquire every slot, then a
        # further non-blocking acquire must fail.
        assert live._MAX_CONCURRENT_DECODES >= 1
        got = [live._decode_sem.acquire(blocking=False)
               for _ in range(live._MAX_CONCURRENT_DECODES)]
        try:
            assert all(got)                                    # all slots free initially
            assert live._decode_sem.acquire(blocking=False) is False   # then bounded
        finally:
            for _ in got:
                live._decode_sem.release()

    def test_decode_sheds_instead_of_parking_a_worker_when_saturated(self):
        # REVERT-FAILING (SEC2, refute 2026-07-20): the decode semaphore is
        # NON-blocking — when all slots are held, decode_frame SHEDS the frame
        # (returns None) rather than parking the worker thread on the semaphore.
        # A blocking acquire here would DEADLOCK this test (all slots held), which
        # is exactly the thread-starvation a burst would cause on the server.
        pytest.importorskip("PIL")
        got = [live._decode_sem.acquire(blocking=False)
               for _ in range(live._MAX_CONCURRENT_DECODES)]
        try:
            assert all(got)
            assert decode_frame(_jpeg()) is None       # shed, did not block/deadlock
        finally:
            for _ in got:
                live._decode_sem.release()
        assert decode_frame(_jpeg()) is not None        # slots freed → decodes again


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

    def test_low_confidence_floor_guess_is_not_shown(self, tmp_path, monkeypatch):
        # REVERT-FAILING (R3, refute 2026-07-20): the local floor must apply the
        # SAME min_confidence gate the world-lens recognizer does. A 0.30 guess
        # the recognizer would reject must NOT sail onto the HUD just because the
        # look fell to the floor — pre-fix _local_look had no gate, so incognito
        # and normal disagreed on the identical frame.
        pytest.importorskip("PIL")
        brain = _brain(tmp_path)
        monkeypatch.setattr(live, "_ladder", lambda arr: ("book", 0.30))
        out = look(brain, _jpeg())
        assert out["ok"] is True and out["label"] == ""     # gated out, honest
        assert out["confidence"] == 0.0
        # a confident hit on the same path still shows
        monkeypatch.setattr(live, "_ladder", lambda arr: ("book", 0.80))
        out2 = look(brain, _jpeg())
        assert out2["label"] == "book"

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
            # nonce-based, no 'unsafe-inline'; the on-device detector adds 'self'
            # + 'wasm-unsafe-eval' (WASM compilation only) — but NEVER the full
            # 'unsafe-eval', and connect-src stays 'self' so nothing egresses.
            assert "'nonce-" in script_dir and "'unsafe-inline'" not in script_dir
            assert "'unsafe-eval'" not in script_dir        # wasm-unsafe-eval ≠ unsafe-eval
            assert "connect-src 'self'" in csp
            assert "'wasm-unsafe-eval'" in script_dir       # the on-device detector needs it
            nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
            assert f'<script nonce="{nonce}">' in page      # header nonce == tag nonce
            assert f'<style nonce="{nonce}">' in page
        finally:
            server.shutdown(); server.server_close()


class TestDetectorAssets:
    """The vendored on-device detector (MediaPipe loader + WASM + int8 model) is
    served SAME-ORIGIN so the in-browser recognizer loads with zero external
    fetch — the CSP forbids off-origin, so the frames never leave the phone."""

    def test_asset_helper_types_and_confines_to_its_dir(self):
        from dreamlayer.ai_brain.server.server import _live_asset
        mjs = _live_asset("vision_bundle.mjs")
        assert mjs is not None and mjs[1] == "text/javascript" and len(mjs[0]) > 1000
        wasm = _live_asset("wasm/vision_wasm_internal.wasm")
        assert wasm is not None and wasm[1] == "application/wasm"
        model = _live_asset("models/efficientdet_lite0.tflite")
        assert model is not None and model[1] == "application/octet-stream"
        # path traversal, unknown extensions, and misses are all refused
        assert _live_asset("../server.py") is None
        assert _live_asset("../../__init__.py") is None
        assert _live_asset("wasm/../../store.py") is None
        assert _live_asset("secret.txt") is None            # unknown extension
        assert _live_asset("models/nope.tflite") is None    # missing file

    def test_vendored_assets_match_their_pinned_hashes(self):
        # Enforce the PROVENANCE.md sha256 pins: a swapped or corrupted detector
        # binary (served to browsers and compiled as WASM) fails CI here instead
        # of only being caught by a human re-running sha256sum (refute 2026-07-20).
        import hashlib
        import re as _re
        base = Path(live.__file__).resolve().parent / "assets" / "mediapipe"
        prov = (base / "PROVENANCE.md").read_text(encoding="utf-8")
        pins = _re.findall(r"\|\s*`([^`]+)`\s*\|\s*`([0-9a-f]{64})`\s*\|", prov)
        assert len(pins) >= 4, f"expected >=4 pinned assets, parsed {len(pins)}"
        for rel, want in pins:
            fp = base / rel
            assert fp.is_file(), f"pinned asset missing: {rel}"
            got = hashlib.sha256(fp.read_bytes()).hexdigest()
            assert got == want, f"{rel} drifted from its PROVENANCE.md sha256"

    def test_assets_route_is_public_and_typed(self, tmp_path):
        # served pre-auth (the page fetches them before pairing) with the right
        # MIME so the browser will execute the module + compile the WASM.
        brain = _brain(tmp_path)
        server, base = _serve(brain)
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(base + "/dreamlayer/live/assets/vision_bundle.mjs",
                             timeout=10) as r:      # no token — public asset
                assert r.status == 200
                assert r.headers.get("Content-Type", "").startswith("text/javascript")
                assert len(r.read()) > 1000
            with opener.open(base + "/dreamlayer/live/assets/wasm/vision_wasm_internal.wasm",
                             timeout=10) as r:
                assert r.headers.get("Content-Type") == "application/wasm"
            # a missing asset is a clean 404, never a 500 or a file leak
            try:
                opener.open(base + "/dreamlayer/live/assets/models/nope.tflite", timeout=10)
                assert False, "missing asset should 404"
            except urllib.error.HTTPError as e:
                assert e.code == 404
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


def _decode_qr_svg(svg: str, scale: int = 6, quiet: int = 4) -> str:
    """Rebuild the module grid from the panel's QR <svg> and decode it back to
    its payload — proving what a phone camera would actually scan."""
    import re

    from dreamlayer.ai_brain.server.qr import decode_matrix
    m = re.search(r'<svg[^>]*width="(\d+)"', svg)
    assert m is not None, "qr svg has no width"
    dim = int(m.group(1))
    n = dim // scale - 2 * quiet
    grid = [[0] * n for _ in range(n)]
    for xs, ys, ws in re.findall(r'<rect x="(\d+)" y="(\d+)" width="(\d+)"', svg):
        x, y, w = int(xs), int(ys), int(ws)
        if w != scale:
            continue
        c, r = x // scale - quiet, y // scale - quiet
        if 0 <= r < n and 0 <= c < n:
            grid[r][c] = 1
    return decode_matrix(grid).decode()


class TestLiveLinkQr:
    """The QR is what the phone actually scans. It must encode the SPARSE short
    code (#c=), not the 32-char token (#t=): a lower QR version → bigger modules
    at the same render → locks on off a glossy screen; the page redeems it on
    load. Copy-link still hands out the full token URL. (refute 2026-07-21: the
    QR encoded the long token link and phones couldn't lock onto it — the typed
    code worked, the scan didn't.)"""

    def test_qr_encodes_the_short_code_not_the_token(self, tmp_path):
        brain = _brain(tmp_path)
        server, base = _serve(brain)
        try:
            status, body = _req(base + "/dreamlayer/live/link",
                                headers={"X-DreamLayer-Token": TOKEN})
            assert status == 200
            out = json.loads(body)
            payload = _decode_qr_svg(out["qr"])
            assert payload.startswith("https://")          # the camera-able link
            assert payload.endswith("#c=" + out["code"])   # the SPARSE code…
            assert TOKEN not in payload                    # …never the token
            assert "#t=" + TOKEN in out["url"]             # copy-link keeps it
        finally:
            server.shutdown(); server.server_close()

    def test_http_only_qr_keeps_the_token_fragment(self, tmp_path):
        # refute F1 (2026-07-21): /live/redeem refuses non-TLS callers, so an
        # http-mode QR carrying #c= could NEVER pair. Without --tls the QR must
        # keep the #t= token link (which never rides the wire at all).
        brain = _brain(tmp_path)
        server = make_brain_server(brain, "127.0.0.1", 0)      # no tls_port
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            status, body = _req(base + "/dreamlayer/live/link",
                                headers={"X-DreamLayer-Token": TOKEN})
            assert status == 200
            out = json.loads(body)
            payload = _decode_qr_svg(out["qr"])
            assert payload.endswith("#t=" + TOKEN)             # pairable over http
            assert "#c=" not in payload
        finally:
            server.shutdown(); server.server_close()

    def test_code_qr_is_a_strictly_smaller_matrix_than_the_token_qr(self):
        # the point of #c=: with the PRODUCTION 32-hex token (token_hex(16)) the
        # code QR is a lower version — bigger modules at the same render size.
        from dreamlayer.ai_brain.server.qr import encode_matrix
        host = "https://192.168.1.42:8443/dreamlayer/live"
        code_n = len(encode_matrix(host + "#c=12345678"))
        token_n = len(encode_matrix(host + "#t=" + "a" * 32))
        assert code_n < token_n, f"code {code_n} not sparser than token {token_n}"

    def test_page_redeems_a_qr_carried_code_on_boot(self):
        # the client half: #c= parsed from the fragment, redeemed via the SAME
        # doRedeem the typed-code modal uses (one implementation, two entries).
        page = render_live()
        assert 'location.hash.startsWith("#c=")' in page
        assert "PENDING_CODE" in page and "function doRedeem" in page


class TestGlassRenderer:
    """The lens circle draws the DEVICE card — a faithful port of the glasses'
    object-family renderer (halo-lua/display/renderer.lua draw_object_recall),
    not an invented phone UI: same 256px space, same geometry, palette.lua
    colors, typography.lua sizes, fed by the same ObjectPanel the Brain built."""

    def test_page_ships_the_device_renderer_port(self):
        page = render_live()
        assert 'id="glass"' in page                       # the 256px round display
        assert "function glassObjectCard" in page
        # geometry verbatim from renderer.lua:596 — jewel at (128,88), you-dot
        # at (128,198), the place field disc at (128,112) r62
        for needle in ("128, 88", "128, 198", "128, 112, 62"):
            assert needle in page, f"device geometry missing: {needle}"
        # palette.lua verbatim
        for hexv in ("#ECF0F1", "#00FFAA", "#B8FFE9", "#FFAA00", "#2A3C44"):
            assert hexv in page, f"palette color missing: {hexv}"
        # typography.lua sizes
        assert "lg:17" in page and "md:13" in page and "sm:10" in page

    def test_glass_clears_under_the_veil(self):
        page = render_live()
        assert "glassClear()" in page
        veil_fn = page.split("function setVeil", 1)[1].split("function ", 1)[0]
        assert "glassClear" in veil_fn


class TestPhoneRunsEveryGlassesLens:
    """Provider parity (refute 2026-07-21): the phone World-lens host must wire
    the SAME built-in provider set the glasses do (orchestrator._init_object_
    lenses: Memory + AI + Label + Rosetta) — previously it registered only
    AIProvider, so a phone look ran a subset of the product's lenses."""

    def test_host_registers_the_full_builtin_set(self, tmp_path):
        brain = _brain(tmp_path)
        wl = brain.world_lens()
        names = {p.name for p in wl.object_lens.registry._providers}
        assert {"memory", "ai", "label", "rosetta"} <= names, names

    def test_seen_before_is_real_ring_memory(self, tmp_path):
        # the same SemanticRingBuffer the glasses run: a second look at the same
        # object recalls the first — and a FIRST look never claims a prior one.
        from dreamlayer.object_lens.schema import ObjectSighting
        brain = _brain(tmp_path)
        wl = brain.world_lens()
        first = wl.look_sighting(ObjectSighting(label="coffee mug", confidence=0.9))
        assert not any("seen before" in r.label for r in first.rows)
        second = wl.look_sighting(ObjectSighting(label="coffee mug", confidence=0.9))
        assert any("seen before" in r.label for r in second.rows)

    def test_seen_before_never_substring_fabricates(self, tmp_path):
        # refute 2026-07-21: "cup" must NOT match a prior "cupboard" — a raw
        # substring test claimed sightings of objects never seen.
        from dreamlayer.object_lens.schema import ObjectSighting
        wl = _brain(tmp_path).world_lens()
        wl.look_sighting(ObjectSighting(label="cupboard", confidence=0.9))
        p = wl.look_sighting(ObjectSighting(label="cup", confidence=0.9))
        assert not any("seen before" in r.label for r in p.rows)

    def test_erase_everything_drops_the_sighting_ring(self, tmp_path):
        # refute 2026-07-21: purge_memories left the cached host (and its
        # ring) alive — pre-erase sightings surfaced on the next look.
        from dreamlayer.object_lens.schema import ObjectSighting
        brain = _brain(tmp_path)
        brain.world_lens().look_sighting(
            ObjectSighting(label="coffee mug", confidence=0.9))
        assert len(brain.world_lens().ring) > 0
        brain.purge_memories()
        assert len(brain.world_lens().ring) == 0

    def test_veiled_look_leaves_no_ring_trace(self, tmp_path):
        # the veil gate runs BEFORE the ring append — a veiled look must not
        # add a sighting the wearer never agreed to remember.
        from dreamlayer.object_lens.schema import ObjectSighting
        brain = _brain(tmp_path, network_mode="lan_only")
        assert brain.incognito_now() is True
        wl = brain.world_lens()
        assert wl.look_sighting(ObjectSighting(label="mug", confidence=0.9)) is None
        assert len(wl.ring) == 0


class TestDreamScope:
    """Dream mode on the live page — the glasses' DOUBLE-TAP grammar and a
    scope of the real DreamEngine models (mic_reactor two-band weather,
    imu_reactor curl field, dream_renderer's 24-particle core at 2 Hz), the
    same way the phone app's DreamCanvas replays them. Client-only; the veil
    WAKES the dream so the mic is released, never merely ignored."""

    def test_page_ships_the_dream_scope(self):
        page = render_live()
        for needle in ("function enterDream", "function exitDream",
                       "function toggleDream", "DREAM_TICK_MS = 500",
                       "devicemotion", 'data-dream'):
            assert needle in page, f"dream piece missing: {needle}"
        # the device models, pinned: 24 particles clipped to r<=96, 12 vectors
        assert "i < 24" in page and "96 - 3" in page and "i < 12" in page

    def test_double_tap_toggles_and_single_tap_still_looks(self):
        page = render_live()
        tap = page.split('$("lens").onclick', 1)[1].split("$(\"lens\").onkeydown", 1)[0]
        assert "toggleDream()" in tap and "lookNow(false)" in tap
        assert "300" in tap                                # the double-tap window

    def test_dream_idles_the_memory_mode_loops(self):
        # DreamEngine replaces memory mode on the glasses — here both the Brain
        # ambient loop and the on-device detector idle while dreaming.
        page = render_live()
        sched = page.split("function scheduleLoop", 1)[1].split("function ", 1)[0]
        assert "dreamOn" in sched
        tick = page.split("function detectTick", 1)[1].split("function ", 1)[0]
        assert "dreamOn" in tick

    def test_veil_wakes_the_dream_and_releases_the_mic(self):
        page = render_live()
        veil_fn = page.split("function setVeil", 1)[1].split("function ", 1)[0]
        assert "exitDream()" in veil_fn
        exit_fn = page.split("function exitDream", 1)[1].split("function ", 1)[0]
        assert "getTracks().forEach(t => t.stop())" in exit_fn   # mic RELEASED


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

    def test_ambient_look_is_local_only_and_leaves_no_trace(self, tmp_path, monkeypatch):
        # A continuous-loop (ambient) frame must NOT consult the world lens /
        # plugins / remote vision, and must write NO ledger entry — otherwise the
        # several-a-minute cadence floods the ledger and could auto-egress every
        # frame to a configured VLM. Only a deliberate tap escalates + records.
        pytest.importorskip("PIL")
        brain = self._world_brain(tmp_path, self.PRICE)   # full VLM + plugin brain
        monkeypatch.setattr(live, "_ladder", lambda arr: ("mug", 0.9))
        # a deliberate tap escalates to the full lens and records the sighting
        tap = look(brain, _jpeg())
        assert tap["label"] == "price tag"
        n_after_tap = sum(1 for i in brain.activity.recent() if i["kind"] == "look")
        assert n_after_tap >= 1
        # now an ambient frame: it must NOT touch the world lens (boom guards that)
        # and must add NO new ledger trace, and egress nothing
        monkeypatch.setattr(brain, "world_lens",
                            lambda: (_ for _ in ()).throw(
                                AssertionError("ambient consulted the world lens")))
        out = look(brain, _jpeg(), ambient=True)
        assert out["ok"] is True and out["label"] == "mug"   # local classifier answered
        assert out["panel"]["rows"] == []                    # shape parity, no providers
        assert brain.config.cloud_calls == 0                 # nothing egressed
        n_after_ambient = sum(1 for i in brain.activity.recent() if i["kind"] == "look")
        assert n_after_ambient == n_after_tap                # ambient left no trace

    def test_smart_path_error_flags_degraded_not_silent(self, tmp_path, monkeypatch):
        # REVERT-FAILING (R2, refute 2026-07-20): when the world lens ERRORS
        # (provider crash, model timeout) the look still falls to the honest floor
        # — but it must SAY it degraded, not silently masquerade the 4-bucket floor
        # as the smart answer. A plain "nothing recognized" is NOT flagged; only a
        # real break is.
        pytest.importorskip("PIL")
        brain = self._world_brain(tmp_path, self.PRICE)
        # a clean look (no error) must NOT be flagged degraded
        clean = look(brain, _jpeg())
        assert clean["label"] == "price tag" and "degraded" not in clean
        # now make the world lens ERROR mid-look — the floor answers, flagged
        wl = brain.world_lens()
        monkeypatch.setattr(wl, "look",
                            lambda arr: (_ for _ in ()).throw(RuntimeError("provider died")))
        monkeypatch.setattr(live, "_ladder", lambda arr: ("mug", 0.9))
        out = look(brain, _jpeg())
        assert out["ok"] is True and out["label"] == "mug"   # floor still answers
        assert out.get("degraded") is True                   # and is honest about it

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
            # The hot ring is REAL now (provider parity 2026-07-21): a second
            # look at the same photo legitimately learns "seen before" — exactly
            # as the glasses would. Comparing the two ROUTES needs equal memory
            # state, so clear the ring between them; the formatter is the claim.
            brain.world_lens().ring.clear()
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
