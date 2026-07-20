"""test_aaa_audit_2026_07_20.py — regression pins for the AAA audit of the
changes since v0.4.0. Every test is revert-failing: undo the matching fix in
server.py / tls.py / backends.py / pokemon_price.py and the assertion breaks.

Closed gaps (audit 2026-07-20):
  M1  model pull + pack install now honor Incognito/LAN-only posture, and the
      pull model name can't repoint the fetch at a non-default registry host.
  M2  auto-TLS cert minting degrades to http-only on a filesystem error instead
      of crashing the Brain (ensure_self_signed moved inside the try/except).
  M3  the state-mutating, egress-causing /plugins/store GET takes the same CSRF
      guard the mutating POSTs do.
  L   shared auth limiter across the HTTP + TLS listeners; bounded pull-job dict;
      bounded NDJSON stream read; Lucene phrase escaping; PII-safe diagnostics
      (URL-ish model redacted); GitHub-issue URL bounded by ENCODED length.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import urllib.error
import urllib.request

import dreamlayer.ai_brain.server.server as srv
from dreamlayer.ai_brain.server import Brain, backends as be, make_brain_server
from dreamlayer.ai_brain.server import tls as tlsmod
from dreamlayer.plugins.pokemon_price import build_query, _lucene


def _brain():
    return Brain(tempfile.mkdtemp())


# --- M1: model pull posture gate + registry-host validation ------------------

def test_model_name_ok_rejects_a_registry_host():
    assert srv._model_name_ok("llama3.2")
    assert srv._model_name_ok("llama3.2:1b")
    assert srv._model_name_ok("library/llama3.2")
    assert not srv._model_name_ok("evil.example.com/backdoor:latest")
    assert not srv._model_name_ok("host:1234/model")
    assert not srv._model_name_ok("has a space")
    assert not srv._model_name_ok("")


def test_pull_refused_in_incognito_and_starts_nothing():
    b = _brain()
    b.config.network_mode = "lan_only"
    srv._PULL_JOBS.clear()
    r = srv._pull_model_async(b, "llama3.2")
    assert "error" in r and "Incognito" in r["error"]
    assert "llama3.2" not in srv._PULL_JOBS          # no thread, no job started
    srv._PULL_JOBS.clear()


def test_pull_rejects_an_external_registry_name():
    b = _brain()
    srv._PULL_JOBS.clear()
    r = srv._pull_model_async(b, "evil.example.com/backdoor")
    assert "error" in r and not srv._PULL_JOBS       # rejected before any pull
    srv._PULL_JOBS.clear()


def test_prune_pull_jobs_drops_stale_terminal_and_caps():
    srv._PULL_JOBS.clear()
    srv._PULL_JOBS["old"] = {"state": "done", "ts": 0.0}
    srv._PULL_JOBS["live"] = {"state": "pulling", "ts": 1e12}
    srv._prune_pull_jobs(1e12)                        # old is way past the TTL
    assert "old" not in srv._PULL_JOBS and "live" in srv._PULL_JOBS
    srv._PULL_JOBS.clear()
    for i in range(srv._PULL_JOBS_MAX + 20):
        srv._PULL_JOBS[f"m{i}"] = {"state": "done", "ts": float(i)}
    srv._prune_pull_jobs(10.0)                        # within TTL → cap eviction
    assert len(srv._PULL_JOBS) <= srv._PULL_JOBS_MAX
    srv._PULL_JOBS.clear()


# --- M1: pack install posture gate + pip index hardening ---------------------

def test_pack_install_refused_in_incognito(monkeypatch):
    b = _brain()
    b.config.network_mode = "lan_only"
    launched: list = []
    monkeypatch.setattr(srv, "_PACK_RUNNER", lambda reqs: launched.append(reqs) or (True, "ok"))
    srv._PACK_JOBS.clear()
    r = srv._install_pack(b, "recall")
    assert "error" in r and "Incognito" in r["error"]
    time.sleep(0.1)
    assert launched == []                             # pip runner never launched
    srv._PACK_JOBS.clear()


def test_pip_env_strips_index_redirect_vars():
    saved = os.environ.get("PIP_INDEX_URL")
    os.environ["PIP_INDEX_URL"] = "http://evil.example/simple"
    try:
        env = srv._pip_env()
        assert "PIP_INDEX_URL" not in env
        assert "PIP_EXTRA_INDEX_URL" not in env and "PIP_CONFIG_FILE" not in env
    finally:
        if saved is None:
            os.environ.pop("PIP_INDEX_URL", None)
        else:
            os.environ["PIP_INDEX_URL"] = saved


# --- M2: auto-TLS degrades to http-only, never crashes -----------------------

def test_tls_sibling_degrades_when_cert_dir_path_is_a_file():
    cfg = tempfile.mkdtemp()
    open(os.path.join(cfg, "tls"), "w").close()       # a FILE where <cfg>/tls dir goes
    server, port = tlsmod.start_tls_sibling(_brain(), "127.0.0.1", cfg, 7777)
    assert server is None and port == 0               # degraded — did NOT raise


# --- M3 + shared limiter: HTTP surface ---------------------------------------

def _serve(brain):
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "127.0.0.1", server.server_address[1]


def _get(url, headers):
    req = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_store_get_refuses_cross_origin_but_allows_same_origin():
    b = _brain()
    b.config.network_mode = "lan_only"          # so store_catalogue short-circuits (no network)
    server, host, port = _serve(b)
    try:
        base = f"http://{host}:{port}/dreamlayer/plugins/store"
        # a page on another origin cannot force the Brain to hit the registry
        assert _get(base, {"Origin": "http://evil.example"}) == 403
        # the panel's own same-origin request is allowed through
        assert _get(base, {"Origin": f"http://{host}:{port}"}) == 200
        # a native/CLI caller with no Origin is allowed (unchanged)
        assert _get(base, {}) == 200
    finally:
        server.shutdown(); server.server_close()


def test_auth_limiter_is_shared_across_listeners():
    b = _brain()
    s1 = make_brain_server(b, "127.0.0.1", 0)
    lim = getattr(b, "_shared_auth_limiter", None)
    assert lim is not None
    s2 = make_brain_server(b, "127.0.0.1", 0)         # the TLS sibling re-enters this
    assert getattr(b, "_shared_auth_limiter") is lim  # reused, not a fresh counter
    s1.server_close(); s2.server_close()


# --- bounded NDJSON pull stream ----------------------------------------------

class _FakeResp:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def read(self, n):
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_opener(chunks):
    class _O:
        def open(self, req, timeout=None):
            return _FakeResp(chunks)
    return lambda *a, **k: _O()


def test_pull_stream_caps_a_newlineless_flood(monkeypatch):
    flood = b"x" * (2 << 20)                             # 2 MiB, no newline
    monkeypatch.setattr(be.urllib.request, "build_opener", _fake_opener([flood]))
    seen: list = []
    try:
        be._urllib_post_stream("http://x", {}, 5.0, seen.append)
        raised = False
    except ValueError:
        raised = True
    assert raised and seen == []                       # capped before OOM, nothing parsed


def test_pull_stream_parses_normal_ndjson(monkeypatch):
    body = b'{"status":"pulling"}\n{"status":"success"}\n'
    monkeypatch.setattr(be.urllib.request, "build_opener", _fake_opener([body]))
    seen: list = []
    be._urllib_post_stream("http://x", {}, 5.0, seen.append)
    assert [o.get("status") for o in seen] == ["pulling", "success"]


# --- Lucene phrase escaping (pokemon-price) ----------------------------------

def test_lucene_neutralises_quote_and_backslash():
    assert '"' not in _lucene('Charizard" OR name:"Mewtwo')
    assert "\\" not in _lucene('a\\b')


def test_build_query_cannot_break_out_of_the_phrase():
    # an injected quote must not create a second unescaped name: clause
    url = build_query('Charizard" OR set.id:"base1')
    assert url.count("name%3A%22") == 1              # exactly one name: phrase
    assert '%22 OR' not in url.replace("%20", " ")   # no live phrase break-out


# --- PII-safe diagnostics + bounded issue URL --------------------------------

def test_report_diagnostics_redacts_a_urlish_model():
    b = _brain()
    b.config.model = "https://evil.example/v1/chat"
    out = srv._report_diagnostics(b)
    assert "evil.example" not in out and "(custom endpoint)" in out
    b.config.model = "llama3.2"
    assert "llama3.2" in srv._report_diagnostics(b)


def test_bug_report_url_bounded_for_multibyte_input():
    b = _brain()
    b.config.model = "llama3.2"
    huge = "日本語テストの説明 " * 2000              # ~24k multibyte chars
    r = srv._build_bug_report(b, "title", huge, include_diag=False)
    assert len(r["github_url"]) <= 6000              # bounded by ENCODED length
    assert len(r["body"]) > 6000                     # full body kept for copy
