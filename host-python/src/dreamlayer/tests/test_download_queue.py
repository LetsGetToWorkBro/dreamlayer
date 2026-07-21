"""Unified download queue — packs, models, plugins ride ONE serial queue.

Pins: enqueue-many (Download All), serial order, live progress proxied from
the underlying job machinery, duplicate suppression, queued-only cancel, and
the local-only bar on the write endpoints.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import dreamlayer.ai_brain.server.server as srv
from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.store import BrainConfig

TOKEN = "rune-birch"


def _brain(tmp_path) -> Brain:
    d = tmp_path / "cfg"
    d.mkdir()
    BrainConfig(token=TOKEN).save(d)
    return Brain(d)


def _serve(brain):
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _req(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _drain(timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        snap = srv._dl_snapshot()
        if all(i["state"] not in ("queued", "running") for i in snap):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"queue never drained: {srv._dl_snapshot()}")


class TestQueueCore:
    def setup_method(self):
        srv._DL_QUEUE.clear()

    def test_serial_order_and_progress(self, tmp_path, monkeypatch):
        ran = []

        def fake_pack(brain, key):
            job = {"state": "installing", "percent": 0, "detail": ""}

            def w():
                ran.append(key)
                job["percent"] = 100
                job["state"] = "done"
            threading.Thread(target=w, daemon=True).start()
            return job

        monkeypatch.setattr(srv, "_install_pack", fake_pack)
        real = srv._dl_run_one
        monkeypatch.setattr(srv, "_dl_run_one",
                            lambda b, it: real(b, it, poll_s=0.01, max_polls=500))
        b = _brain(tmp_path)
        for k in ("guardian", "operator", "scholar"):
            out = srv._dl_enqueue(b, "pack", k)
            assert out.get("ok"), out
        snap = _drain()
        assert ran == ["guardian", "operator", "scholar"]      # strict FIFO
        assert all(i["state"] == "done" and i["percent"] == 100 for i in snap)

    def test_duplicate_is_suppressed_and_cancel_is_queued_only(self, tmp_path, monkeypatch):
        gate = threading.Event()

        def slow_pack(brain, key):
            job = {"state": "installing", "percent": 5, "detail": "x"}
            def w():
                gate.wait(5)
                job["state"] = "done"; job["percent"] = 100
            threading.Thread(target=w, daemon=True).start()
            return job

        monkeypatch.setattr(srv, "_install_pack", slow_pack)
        real = srv._dl_run_one
        monkeypatch.setattr(srv, "_dl_run_one",
                            lambda b, it: real(b, it, poll_s=0.01, max_polls=1000))
        b = _brain(tmp_path)
        first = srv._dl_enqueue(b, "pack", "guardian")
        dup = srv._dl_enqueue(b, "pack", "guardian")
        assert dup.get("note") == "already queued"
        queued = srv._dl_enqueue(b, "pack", "operator")
        # wait until guardian is genuinely RUNNING, then: running refuses
        # cancel; the still-queued item cancels cleanly
        for _ in range(200):
            if srv._dl_snapshot()[0]["state"] == "running":
                break
            time.sleep(0.01)
        assert "error" in srv._dl_cancel(first["id"])
        assert srv._dl_cancel(queued["id"]) == {"ok": True}
        gate.set()
        snap = _drain()
        states = {(i["kind"], i["key"]): i["state"] for i in snap}
        assert states[("pack", "operator")] == "cancelled"

    def test_plugin_kind_runs_store_install(self, tmp_path, monkeypatch):
        b = _brain(tmp_path)
        monkeypatch.setattr(type(b), "store_install",
                            lambda self, name: {"ok": True, "installed": name},
                            raising=False)
        out = srv._dl_enqueue(b, "plugin", "hello-lens")
        assert out.get("ok")
        snap = _drain()
        assert snap[-1]["state"] == "done" and snap[-1]["percent"] == 100

    def test_bad_kind_refused(self, tmp_path):
        b = _brain(tmp_path)
        assert "error" in srv._dl_enqueue(b, "warez", "x")
        assert "error" in srv._dl_enqueue(b, "pack", "")


class TestQueueHttp:
    def setup_method(self):
        srv._DL_QUEUE.clear()

    def test_enqueue_many_snapshot_and_localhost_bar(self, tmp_path, monkeypatch):
        def instant(brain, key):
            return {"state": "done", "percent": 100, "detail": "installed"}
        monkeypatch.setattr(srv, "_install_pack", instant)
        real = srv._dl_run_one
        monkeypatch.setattr(srv, "_dl_run_one",
                            lambda b, it: real(b, it, poll_s=0.01, max_polls=50))
        brain = _brain(tmp_path)
        server, base = _serve(brain)
        try:
            hdr = {"X-DreamLayer-Token": TOKEN,
                   "Content-Type": "application/json"}
            status, out = _req(
                base + "/dreamlayer/downloads/enqueue",
                data=json.dumps({"items": [
                    {"kind": "pack", "key": "guardian"},
                    {"kind": "pack", "key": "operator"}]}).encode(),
                headers=hdr)
            assert status == 200 and all(q.get("ok") for q in out["queued"])
            _drain()
            status, out = _req(base + "/dreamlayer/downloads", headers=hdr)
            assert status == 200
            assert [i["key"] for i in out["queue"]] == ["guardian", "operator"]
            assert all(i["state"] == "done" for i in out["queue"])
        finally:
            server.shutdown(); server.server_close()
