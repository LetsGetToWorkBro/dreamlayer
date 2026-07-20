"""test_setup_ux_2026_07_19.py — pre-release setup-UX polish.

Three fixes so the app is easy to start out of the box, each revert-failing:

  Live Lens auto-TLS — a phone browser opens its camera only on a SECURE
     context, but TLS was opt-in (--tls), so the packaged app served the Live
     Lens over http and scanning the QR did nothing. Now the https sibling
     listener starts AUTOMATICALLY for a network-reachable bind (and always in
     the bundled app), and the panel walks the wearer through the cert prompt.

  Ollama pull progress — a multi-GB pull ran as ONE blocking request that timed
     the browser out with no progress ("can't pull"). Now it's a background job
     that STREAMS Ollama's progress into a poll the panel renders as a live %.

  One-click packs in the frozen app — a sealed bundle can't pip-install into
     itself, so optional capabilities said "runs on a source install". Now packs
     install into a writable sidecar (<cfg>/site-packages, on sys.path) via pip
     --target, so the bundled app installs them one-click too.
"""
from __future__ import annotations

import sys
import types

import pytest

import dreamlayer.ai_brain.server.server as srv
import dreamlayer.ai_brain.server.backends as backends
import dreamlayer.ai_brain.server.tls as tlsmod
import dreamlayer.capabilities as caps
from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.panel import render_panel


# ===========================================================================
# Live Lens auto-TLS
# ===========================================================================

def test_start_tls_sibling_none_without_cryptography(monkeypatch, tmp_path):
    # ensure_self_signed → None (cryptography absent) must degrade to (None, 0),
    # never crash — the caller then serves http only.
    monkeypatch.setattr(tlsmod, "ensure_self_signed", lambda d: None)
    server, port = tlsmod.start_tls_sibling(Brain(tmp_path), "0.0.0.0", tmp_path, 7777)
    assert server is None and port == 0


def test_start_tls_sibling_starts_https_when_available(tmp_path):
    if tlsmod.ensure_self_signed(tmp_path) is None:
        pytest.skip("cryptography not installed")
    brain = Brain(tmp_path)
    server, port = tlsmod.start_tls_sibling(brain, "127.0.0.1", tmp_path, 7777)
    try:
        assert server is not None
        assert port == 7778                        # default: http_port + 1
        assert getattr(server, "tls_port", None) == 7778
    finally:
        if server is not None:
            server.shutdown(); server.server_close()


def test_main_auto_enables_tls_only_for_network_binds(tmp_path, monkeypatch):
    # The bare LOOPBACK launch must NOT start TLS (keeps the pinned call shape),
    # while a 0.0.0.0 bind auto-starts it. We spy start_tls_sibling + stop before
    # serve_forever.
    from dreamlayer.ai_brain.server import __main__ as m
    started = {}

    def fake_start(brain, host, cfg, port, tls_port=0):
        started["called"] = host
        return None, 0                             # pretend crypto absent → http only

    class _Stop(Exception):
        pass

    def _stop_server(*a, **k):
        raise _Stop

    monkeypatch.setattr(m, "make_brain_server", _stop_server)
    monkeypatch.setattr("dreamlayer.ai_brain.server.tls.start_tls_sibling", fake_start)

    # loopback bare launch → no TLS attempt
    started.clear()
    try:
        m.main(["--dir", str(tmp_path / "a")])
    except _Stop:
        pass
    assert "called" not in started

    # network-reachable bind → TLS attempted
    started.clear()
    try:
        m.main(["--dir", str(tmp_path / "b"), "--host", "0.0.0.0"])
    except _Stop:
        pass
    assert started.get("called") == "0.0.0.0"


def test_main_no_tls_flag_disables_even_on_lan(tmp_path, monkeypatch):
    from dreamlayer.ai_brain.server import __main__ as m
    started = {}
    monkeypatch.setattr("dreamlayer.ai_brain.server.tls.start_tls_sibling",
                        lambda *a, **k: started.setdefault("called", True) or (None, 0))

    class _Stop(Exception):
        pass
    monkeypatch.setattr(m, "make_brain_server", lambda *a, **k: (_ for _ in ()).throw(_Stop()))
    try:
        m.main(["--dir", str(tmp_path), "--host", "0.0.0.0", "--no-tls"])
    except _Stop:
        pass
    assert "called" not in started


def test_live_link_advertises_https_when_tls_port_set(tmp_path):
    # _get_live_link builds the https URL (the secure one the camera needs) when
    # the server was told a tls_port.
    brain = Brain(tmp_path)          # tokenless loopback → authed as localhost
    server = make_brain_server(brain, "127.0.0.1", 0, tls_port=8788)
    import threading, urllib.request, json
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(f"http://127.0.0.1:{port}/dreamlayer/live/link")
        with opener.open(req, timeout=5) as r:
            data = json.loads(r.read())
        assert data["https"] is True
        assert data["url"].startswith("https://")
        assert ":8788/" in data["url"]
    finally:
        server.shutdown(); server.server_close()


def test_lan_ip_prefers_reachable_home_lan_over_vpn(monkeypatch):
    # REVERT-FAILING (refute 2026-07-20): the single default-route probe returns
    # the VPN/tunnel address on a full-tunnel host, so the QR advertised an IP the
    # phone on the Wi-Fi LAN can't reach → silent dead link. lan_ip() must prefer a
    # real home-LAN address (192.168/x) over the 10/x the probe/VPN handed back.
    monkeypatch.setattr(srv, "_route_probe_ip", lambda: "10.8.0.3")   # the VPN IP
    monkeypatch.setattr(srv.socket, "gethostbyname_ex",
                        lambda h: (h, [], ["127.0.1.1", "10.8.0.3", "192.168.1.24"]))
    cands = srv.lan_ip_candidates()
    assert cands[0] == "192.168.1.24"                # home-LAN wins the ordering
    assert "127.0.1.1" not in cands                  # loopback filtered out
    assert srv.lan_ip() == "192.168.1.24"            # ...and that's what the QR uses


def test_lan_ip_candidates_are_private_only_and_deterministic(monkeypatch):
    monkeypatch.setattr(srv, "_route_probe_ip", lambda: "203.0.113.9")  # a PUBLIC ip
    monkeypatch.setattr(srv.socket, "gethostbyname_ex",
                        lambda h: (h, [], ["169.254.5.5", "172.16.4.4", "192.168.0.9"]))
    cands = srv.lan_ip_candidates()
    assert "203.0.113.9" not in cands                # public address never advertised
    assert "169.254.5.5" not in cands                # link-local filtered out
    assert cands == ["192.168.0.9", "172.16.4.4"]    # ranked, stable
    assert srv.lan_ip_candidates() == cands          # deterministic across calls


def test_tls_cert_names_every_lan_candidate(tmp_path, monkeypatch):
    # The cert SANs must include ALL private LAN IPs, so whichever the phone dials
    # (multi-NIC, or after a DHCP change) the cert matches — not just the one the
    # default-route probe happened to pick.
    monkeypatch.setattr(srv, "_route_probe_ip", lambda: "192.168.1.24")
    monkeypatch.setattr(srv.socket, "gethostbyname_ex",
                        lambda h: (h, [], ["192.168.1.24", "10.0.0.7"]))
    paths = tlsmod.ensure_self_signed(tmp_path)
    if paths is None:
        pytest.skip("cryptography not installed")
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(paths[0].read_bytes())
    san_ips = tlsmod._san_ips(cert)
    assert "192.168.1.24" in san_ips and "10.0.0.7" in san_ips
    assert "127.0.0.1" in san_ips


def test_panel_live_setup_walks_through_the_cert_prompt():
    html = render_panel("tok")
    assert "copyLiveLink" in html                  # tap-to-copy fallback exists
    assert "ol class=\"steps\"" in html or "class=\"steps\"" in html
    assert "Advanced" in html and "camera" in html.lower()   # the cert-accept step


# ===========================================================================
# Ollama pull — background job + streamed progress
# ===========================================================================

def _cfg(url="http://127.0.0.1:11434"):
    return types.SimpleNamespace(ollama_url=url)


def test_pull_model_stream_reports_progress_and_success():
    seen = []

    def fake_stream(url, payload, timeout, cb):
        assert payload["stream"] is True
        cb({"status": "pulling manifest"})
        cb({"status": "pulling ab12", "total": 100, "completed": 40})
        cb({"status": "pulling ab12", "total": 100, "completed": 100})
        cb({"status": "success"})

    res = backends.pull_model_stream(_cfg(), "llama3.2-vision",
                                     on_progress=lambda p, d: seen.append(p),
                                     streamer=fake_stream)
    assert res["ok"] is True
    assert 40 in seen and 100 in seen             # progress percentages surfaced


def test_pull_model_stream_surfaces_an_error_without_success():
    def fake_stream(url, payload, timeout, cb):
        cb({"error": "model 'nope' not found"})

    res = backends.pull_model_stream(_cfg(), "nope", streamer=fake_stream)
    assert res["ok"] is False
    assert "not found" in res["status"]


def test_pull_model_stream_unreachable_ollama_is_reported_not_raised():
    def boom(url, payload, timeout, cb):
        raise OSError("connection refused")

    res = backends.pull_model_stream(_cfg(), "llama3.2", streamer=boom)
    assert res["ok"] is False
    assert "could not reach Ollama" in res["status"]


def test_async_pull_starts_immediately_and_finishes(tmp_path, monkeypatch):
    brain = Brain(tmp_path)
    # a slow-ish streamer so the returned job is observably "pulling" first
    import threading
    gate = threading.Event()

    def fake_stream(cfg, name, on_progress=None):
        on_progress and on_progress(30, "pulling")
        gate.wait(2)
        on_progress and on_progress(100, "success")
        return {"ok": True, "status": "success", "model": name}

    monkeypatch.setattr(backends, "pull_model_stream", fake_stream)
    srv._PULL_JOBS.clear()
    job = srv._pull_model_async(brain, "llama3.2-vision")
    assert job["state"] == "pulling"              # returned instantly, not after the download
    assert srv._PULL_JOBS["llama3.2-vision"]["percent"] in (0, 30)
    gate.set()
    import time
    for _ in range(50):
        if srv._PULL_JOBS["llama3.2-vision"]["state"] == "done":
            break
        time.sleep(0.05)
    assert srv._PULL_JOBS["llama3.2-vision"]["state"] == "done"
    assert srv._PULL_JOBS["llama3.2-vision"]["percent"] == 100


def test_async_pull_rejects_empty_name(tmp_path):
    assert srv._pull_model_async(Brain(tmp_path), "")["error"]


def test_model_status_endpoint_includes_pull_progress(tmp_path, monkeypatch):
    brain = Brain(tmp_path)
    monkeypatch.setattr(backends, "probe_ollama",
                        lambda cfg: {"reachable": True, "url": "u",
                                     "want": {}, "have": {}})
    srv._PULL_JOBS.clear()
    srv._PULL_JOBS["llama3.2-vision"] = {"state": "pulling", "percent": 55, "detail": "x"}
    server = make_brain_server(brain, "127.0.0.1", 0)
    import threading, urllib.request, json
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/dreamlayer/model/status", timeout=5) as r:
            data = json.loads(r.read())
        assert data["pulls"]["llama3.2-vision"]["percent"] == 55
    finally:
        srv._PULL_JOBS.clear()
        server.shutdown(); server.server_close()


def test_panel_pull_renders_progress_and_polls():
    html = render_panel("tok")
    assert "pbar" in html                          # the progress-bar element
    assert "r.pulls" in html or "pulls[" in html   # reads live pull state
    assert "setTimeout(checkModel" in html         # keeps polling while pulling


# ===========================================================================
# One-click packs in the frozen app (sidecar)
# ===========================================================================

def test_pack_site_dir_and_enable(tmp_path):
    side = caps.pack_site_dir(tmp_path)
    assert side.name == "site-packages"
    caps.enable_pack_site(tmp_path)
    assert str(side) in sys.path
    assert side.is_dir()


def test_pack_installer_available_matrix(monkeypatch):
    # non-frozen → always installable
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert caps.pack_installer_available() is True
    # frozen + pip importable → installable
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(caps, "find_spec", lambda n: object())
    assert caps.pack_installer_available() is True
    # frozen + NO pip → not installable (the honest source-install case)
    monkeypatch.setattr(caps, "find_spec", lambda n: None)
    assert caps.pack_installer_available() is False


def test_install_pack_routes_source_vs_frozen(tmp_path, monkeypatch):
    brain = Brain(tmp_path)
    monkeypatch.setattr(caps, "pack_requirements", lambda k: ["pkg==1"] if k == "recall" else [])
    env_calls, frozen_calls = [], []
    monkeypatch.setattr(srv, "_PACK_RUNNER", lambda reqs: env_calls.append(reqs) or (True, "ok"))
    monkeypatch.setattr(srv, "_PACK_RUNNER_FROZEN",
                        lambda reqs, target: frozen_calls.append((reqs, target)) or (True, "ok"))
    import time

    monkeypatch.delattr(sys, "frozen", raising=False)
    srv._PACK_JOBS.clear(); srv._install_pack(brain, "recall"); time.sleep(0.2)
    assert env_calls and not frozen_calls          # source → env pip

    env_calls.clear()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    srv._PACK_JOBS.clear(); srv._install_pack(brain, "recall"); time.sleep(0.2)
    assert frozen_calls and not env_calls          # frozen → sidecar --target
    assert frozen_calls[0][1].endswith("site-packages")


def test_run_pip_target_degrades_when_pip_absent(monkeypatch):
    # If a frozen build carries no pip, the runner fails cleanly (no crash) so the
    # panel keeps the honest "source install" wording.
    import builtins
    real_import = builtins.__import__

    def no_pip(name, *a, **k):
        if name.startswith("pip"):
            raise ImportError("no pip in this build")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_pip)
    ok, detail = srv._run_pip_target(["pkg==1"], "/tmp/sidecar")
    assert ok is False
    assert "can't add packs" in detail


def test_capability_payload_exposes_pack_installable(tmp_path):
    brain = Brain(tmp_path)
    payload = srv._capability_payload(brain)
    assert "pack_installable" in payload
    assert "frozen" in payload


def test_panel_gates_install_on_pack_installable():
    html = render_panel("tok")
    # the panel decides the one-click affordance on pack_installable, not frozen
    assert "CAPINSTALL" in html
    assert "pack_installable" in html
