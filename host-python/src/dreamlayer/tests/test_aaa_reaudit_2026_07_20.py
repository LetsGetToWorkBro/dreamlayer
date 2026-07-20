"""test_aaa_reaudit_2026_07_20.py — regression pins for the AAA *re-audit* (the
"audit your audit" pass). Five independent adversarial auditors found gaps in
the PR #495 fixes (three of five had a real hole the same-session review missed)
plus one previously-un-audited surface (a panel XSS). Every test is
revert-failing.

Closed:
  * probe_ollama egressed to a remote ollama_url under Incognito (the pull's
    missed sibling call-site) — now posture-gated at the primitive.
  * _model_name_ok let a single-label registry host (`evilhost/ns/model`) pin a
    non-default host — now rejected by Ollama's component-count rule.
  * the /plugins/store CSRF guard was vacuous vs a no-Origin GET — now a POST.
  * LockoutLimiter had no lock (raced across the shared HTTP+TLS pools) — locked.
  * model-status leaked the raw pull `detail` (echoes the endpoint) off-box.
  * bug-report redaction missed bare host:port / IP / filesystem paths.
  * _PULL_JOBS "pulling" entries were unbounded — global in-flight cap added.
  * store-install / packs (installing code) were not local-only.
  * panel inline-handler XSS: esc() is the wrong escaper for a JS string in an
    onclick; path sinks now use esc(JSON.stringify(x)).
"""
from __future__ import annotations

import tempfile
import threading
import urllib.error
import urllib.request

import dreamlayer.ai_brain.server.server as srv
from dreamlayer.ai_brain.server import Brain, backends as be, make_brain_server
from dreamlayer.ai_brain.server.panel import render_panel
from dreamlayer.pairing_ratelimit import LockoutLimiter


def _brain():
    return Brain(tempfile.mkdtemp())


def _serve(brain):
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "127.0.0.1", server.server_address[1]


class _Cfg:
    ollama_chat_model = ""
    ollama_vision_model = ""
    ollama_embed_model = ""
    lan_only = False
    quiet_hours = ""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# --- probe_ollama posture (the missed sibling call-site) ---------------------

def test_probe_ollama_skips_remote_egress_under_incognito(monkeypatch):
    calls = []
    monkeypatch.setattr(be, "_urllib_get", lambda url, t=4.0: calls.append(url) or {"models": []})
    out = be.probe_ollama(_Cfg(ollama_url="http://gpu.example.net:11434", lan_only=True))
    assert out["reachable"] is False and out.get("blocked") == "posture"
    assert calls == []                                   # no network call was made


def test_probe_ollama_still_probes_localhost_under_incognito(monkeypatch):
    calls = []
    monkeypatch.setattr(be, "_urllib_get", lambda url, t=4.0: calls.append(url) or {"models": []})
    be.probe_ollama(_Cfg(ollama_url="http://127.0.0.1:11434", lan_only=True))
    assert calls == ["http://127.0.0.1:11434/api/tags"]  # localhost probe is not egress


# --- model-name registry-host validation (single-label host bypass) ----------

def test_model_name_rejects_single_label_registry_host():
    assert srv._model_name_ok("llama3.2")
    assert srv._model_name_ok("qwen2.5:7b")
    assert srv._model_name_ok("library/llama3.2")
    assert srv._model_name_ok("user/model:tag")
    assert not srv._model_name_ok("evilhost/ns/model")   # 3 parts → explicit host
    assert not srv._model_name_ok("evil.com/model")      # dotted first part
    assert not srv._model_name_ok("host:1234/model")     # port in first part
    assert not srv._model_name_ok("/evil.com/m")         # leading slash → 3 parts


# --- LockoutLimiter thread-safety --------------------------------------------

def test_lockout_limiter_is_locked_and_race_free():
    lim = LockoutLimiter(max_attempts=5, window_s=60, lockout_s=300)
    assert hasattr(lim, "_lock")                         # revert removes the lock
    errs = []

    def hammer(i):
        try:
            for j in range(2500):                        # distinct keys → force _prune
                lim.record_failure(f"t{i}-k{j}")         # eviction under concurrency
                lim.allow(f"t{i}-k{j}")
        except Exception as e:                           # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=hammer, args=(i,)) for i in range(8)]  # >4096 keys
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errs == []                                    # no RuntimeError from the race


# --- HTTP: off-box detail strip + install local-only -------------------------

def _req(url, headers, method="GET", body=None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_model_status_strips_pull_detail_for_off_box_callers():
    import json
    b = _brain()
    b.config.token = "tok"                               # so an off-box caller can auth
    srv._PULL_JOBS.clear()
    srv._PULL_JOBS["m"] = {"state": "failed", "percent": 0,
                           "detail": "could not reach Ollama: http://10.0.0.5:11434/api/pull",
                           "ts": 1e12}
    server, host, port = _serve(b)
    server.RequestHandlerClass._from_localhost = lambda self: False   # force off-box
    try:
        st, raw = _req(f"http://{host}:{port}/dreamlayer/model/status",
                       {srv.TOKEN_HEADER: "tok"})
        assert st == 200
        data = json.loads(raw)
        assert "10.0.0.5" not in json.dumps(data)        # endpoint never leaves the box
        assert data["pulls"]["m"].get("detail") is None  # detail withheld off-box
        assert data["pulls"]["m"]["state"] == "failed"   # state/percent still available
    finally:
        server.shutdown(); server.server_close(); srv._PULL_JOBS.clear()


def test_installing_code_is_local_only():
    b = _brain()
    b.config.token = "tok"
    b.config.network_mode = "lan_only"                   # installs short-circuit anyway
    server, host, port = _serve(b)
    server.RequestHandlerClass._from_localhost = lambda self: False   # force off-box
    try:
        for path in ("/dreamlayer/plugins/store/install", "/dreamlayer/packs"):
            st, _ = _req(f"http://{host}:{port}{path}",
                         {srv.TOKEN_HEADER: "tok", "Content-Type": "application/json"},
                         method="POST", body=b"{}")
            assert st == 403, f"{path} should be local-only, got {st}"
    finally:
        server.shutdown(); server.server_close()


# --- bug-report redaction leak-shapes ----------------------------------------

def test_report_diagnostics_redacts_hostport_ip_and_path():
    b = _brain()
    for leaky in ("evil.com:11434", "10.0.0.5", "192.168.1.42:1234",
                  "/Users/alice/models/secret-nda.gguf", "my-macmini.local:11434",
                  "https://evil.example/v1", "user@host"):
        b.config.model = leaky
        out = srv._report_diagnostics(b)
        assert "(custom)" in out, f"{leaky!r} not redacted"
        # none of the sensitive substrings survive (usernames, IPs, hosts, ports)
        for frag in ("alice", "evil.com", "evil.example", "10.0.0.5",
                     "192.168.1.42", "macmini", "11434"):
            if frag in leaky:
                assert frag not in out, f"{frag!r} leaked from {leaky!r}"
    b.config.model = "llama3.2"                           # a plain ref still shows
    assert "llama3.2" in srv._report_diagnostics(b)


# --- pull in-flight cap ------------------------------------------------------

def test_pull_refused_past_the_inflight_cap():
    b = _brain()
    srv._PULL_JOBS.clear()
    for i in range(srv._PULL_MAX_INFLIGHT):              # fill the cap with in-flight jobs
        srv._PULL_JOBS[f"m{i}"] = {"state": "pulling", "percent": 0, "ts": 1e12}
    r = srv._pull_model_async(b, "one-more-model")
    assert "error" in r and "too many" in r["error"].lower()
    assert "one-more-model" not in srv._PULL_JOBS         # not started
    srv._PULL_JOBS.clear()


# --- panel inline-handler XSS (path sinks) -----------------------------------

def test_panel_path_sinks_use_json_stringify_not_raw_esc():
    html = render_panel("tok")
    # the wrong-context single-quote-hugging pattern is gone for the path sinks
    for bad in ("rmFolder('${esc(f)}')", "browseTo('${esc(r.parent)}')",
                "browseTo('${esc(full)}')"):
        assert bad not in html, f"XSS anti-pattern still present: {bad}"
    # and the correct escaper is used instead
    assert "rmFolder(${esc(JSON.stringify(f))})" in html
    assert "browseTo(${esc(JSON.stringify(full))})" in html
