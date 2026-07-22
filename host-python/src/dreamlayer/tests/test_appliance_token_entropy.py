"""test_appliance_token_entropy.py — the bundled double-click appliance
(``packaging/app_main.py``) must mint a pairing token at least as strong as the
launcher's.

app_main._serve binds 0.0.0.0 (LAN-reachable), so the first-run token it mints
is network-exposed and must match ai_brain.server.__main__ (128-bit,
token_hex(16)) — a 64-bit token_hex(8) was brute-forceable by comparison (audit
2026-07-17). app_main lives in packaging/, outside the importable `dreamlayer`
package, so it's loaded from its file path; the assertions are pure Python and
run on Linux CI (no server ever binds — make_brain_server is faked).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


class _Stop(Exception):
    """Sentinel to unwind _serve right after the token is minted, before any
    real socket bind."""


def _load_app_main():
    path = Path(__file__).resolve().parents[3] / "packaging" / "app_main.py"
    spec = importlib.util.spec_from_file_location("dl_app_main_undertest", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_frozen_appliance_mints_128bit_token(tmp_path, monkeypatch):
    app_main = _load_app_main()
    import dreamlayer.ai_brain.server.server as srv

    class _Cfg:
        def __init__(self):
            self.token = ""

    class _FakeBrain:
        def __init__(self, cfg_dir):
            self.config = _Cfg()

        def save(self):
            pass

        def start_watching(self):
            pass

        def start_brief_scheduler(self):
            pass

        def start_calendar_sync(self):
            pass

        def start_source_sync(self):
            pass

        def start_ear(self):
            pass

    captured: dict = {}

    class _FakeServer:
        def serve_forever(self):
            raise _Stop()

    def _fake_make(brain, host, port, tls_port=None):
        captured["token"] = brain.config.token
        captured["host"] = host
        return _FakeServer()

    # _serve re-imports Brain/make_brain_server from this module on each call,
    # so patching the module attributes is enough; the real secrets.token_hex
    # still runs, so the token's length reflects the byte count the code chose.
    monkeypatch.setattr(srv, "Brain", _FakeBrain)
    monkeypatch.setattr(srv, "make_brain_server", _fake_make)
    # the appliance now auto-starts the Live Lens https sibling; stub it out so
    # this token test stays about the token, not TLS.
    import dreamlayer.ai_brain.server.tls as _tlsmod
    monkeypatch.setattr(_tlsmod, "start_tls_sibling", lambda *a, **k: (None, 0))

    with pytest.raises(_Stop):
        app_main._serve(str(tmp_path), 7777)

    token = captured["token"]
    # 16 bytes → 32 hex chars = 128-bit. token_hex(8) (the reverted state) is
    # 16 chars = 64-bit, which fails here.
    assert len(token) == 32
    assert all(c in "0123456789abcdef" for c in token)
    # sanity: it is the network-exposed bind whose token this guards
    assert captured["host"] == "0.0.0.0"


def test_app_main_has_no_64bit_mint_left(tmp_path):
    # belt-and-suspenders against a re-introduced token_hex(8): the appliance's
    # mint must not be weaker than the 128-bit launcher.
    path = Path(__file__).resolve().parents[3] / "packaging" / "app_main.py"
    src = path.read_text()
    assert "token_hex(8)" not in src
    assert "token_hex(16)" in src
