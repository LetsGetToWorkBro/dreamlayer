"""test_brain_csrf_write_guard.py — the Brain refuses forged cross-origin writes.

Audit (2026-07-15) of the new primary-API-brain tier (#364/#365): a tokenless
loopback Brain authorizes any local caller, and _body() parses a request body
whatever its Content-Type is. That is CSRF-able — a page the wearer merely
visits can fire a *simple* cross-origin POST (text/plain body, no CORS
preflight) at http://127.0.0.1:<port>/dreamlayer/config and, without reading the
response, repoint the primary answer tier (model=api + api_base_url) at an
attacker endpoint, silently exfiltrating every later non-incognito query and
forging the answers the wearer sees.

The fix is a same-origin write guard: browsers attach an unforgeable Origin
header to every cross-origin POST, so a mutating request whose Origin is present
and does not match the Host it arrived on is refused (403). Native callers (the
phone) and CLI tools send no Origin and are unaffected; the same-origin panel's
Origin always matches. These tests are revert-failing — drop the guard and the
forged config write lands.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from dreamlayer.ai_brain.server import Brain, make_brain_server


def _serve(cfg_dir):
    brain = Brain(cfg_dir)
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return brain, server, f"http://127.0.0.1:{server.server_address[1]}"


def _post(url, body, headers, method="POST"):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def test_forged_cross_origin_config_write_is_refused(tmp_path):
    # SECURITY (revert-failing): a cross-origin POST — the attacker's page can
    # only send a *simple* request (text/plain dodges preflight) but the browser
    # still stamps the foreign Origin — must NOT be able to repoint the primary
    # answer tier. Without the guard this 200s and flips model->api.
    brain, server, url = _serve(tmp_path)
    try:
        status, _ = _post(
            url + "/dreamlayer/config",
            {"model": "api", "api_base_url": "https://attacker.example",
             "api_provider": "custom", "api_model": "x"},
            {"Content-Type": "text/plain", "Origin": "https://attacker.example"},
        )
        assert status == 403                       # refused before it can apply
        assert brain.config.model != "api"          # config untouched
        assert brain.config.api_base_url == ""      # no attacker endpoint wired
    finally:
        server.shutdown()


def test_same_origin_panel_write_still_works(tmp_path):
    # the panel is served same-origin, so its Origin equals the Host it posts to.
    brain, server, url = _serve(tmp_path)
    host = url.split("//", 1)[1]                    # 127.0.0.1:<port>
    try:
        status, _ = _post(
            url + "/dreamlayer/config",
            {"model": "api", "api_base_url": "http://localhost:11434",
             "api_provider": "ollama", "api_model": "llama3.2"},
            {"Content-Type": "application/json", "Origin": url},
        )
        assert status == 200
        assert brain.config.model == "api"          # the wearer's own change lands
        assert host  # sanity: Host and Origin share the netloc the guard compares
    finally:
        server.shutdown()


def test_native_caller_without_origin_still_works(tmp_path):
    # the phone (React-Native networking) and CLI tools send no Origin header,
    # so a token/loopback-authorized write is unaffected by the guard.
    brain, server, url = _serve(tmp_path)
    try:
        status, _ = _post(
            url + "/dreamlayer/config",
            {"model": "keyword"},
            {"Content-Type": "application/json"},   # no Origin
        )
        assert status == 200
    finally:
        server.shutdown()


def test_cross_site_localhost_other_port_is_refused(tmp_path):
    # defense in depth: a malicious server on another loopback port is still a
    # different Origin, so it cannot forge a write either.
    brain, server, url = _serve(tmp_path)
    try:
        status, _ = _post(
            url + "/dreamlayer/config",
            {"model": "api", "api_base_url": "https://attacker.example"},
            {"Content-Type": "text/plain", "Origin": "http://127.0.0.1:59999"},
        )
        assert status == 403
        assert brain.config.model != "api"
    finally:
        server.shutdown()
