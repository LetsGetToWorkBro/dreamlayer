"""Brain server × capabilities — the panel's Capabilities view backend:
GET the live report, one-click POST toggles persisted in config (the durable
twin of DL_DISABLE_*), token gating, and the panel markup carrying the view."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from dreamlayer.ai_brain.server import Brain, BrainConfig, make_brain_server
from dreamlayer.capabilities import CAPABILITIES


def _req(url, payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None


class _Live:
    def __init__(self, tmp_path, token="tok"):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token=token).save(cfg)
        self.cfg_dir = cfg
        self.brain = Brain(cfg)
        self.server = make_brain_server(self.brain, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.h = {"X-DreamLayer-Token": token}

    def stop(self):
        self.server.shutdown(); self.server.server_close()


def test_capabilities_report_over_http(tmp_path):
    lb = _Live(tmp_path)
    try:
        status, body = _req(lb.url + "/dreamlayer/capabilities", headers=lb.h)
        assert status == 200
        assert len(body["items"]) == len(CAPABILITIES)
        assert body["disabled"] == [] and body["frozen"] is False
        assert set(body["profiles"]) == {"profile-halo", "profile-phone",
                                         "profile-mac", "profile-cloud"}
        assert sum(body["summary"].values()) == len(CAPABILITIES)
        # every row carries what the panel renders
        row = body["items"][0]
        assert {"key", "tier", "title", "state", "extra", "note"} <= set(row)
    finally:
        lb.stop()


def test_capabilities_requires_token(tmp_path):
    lb = _Live(tmp_path)
    try:
        status, _ = _req(lb.url + "/dreamlayer/capabilities")   # no token header
        assert status == 401
    finally:
        lb.stop()


def test_toggle_persists_and_reflects(tmp_path):
    lb = _Live(tmp_path)
    try:
        # switch one off
        status, body = _req(lb.url + "/dreamlayer/capabilities",
                            {"key": "vector_search", "disabled": True}, lb.h)
        assert status == 200 and body["disabled"] == ["vector_search"]
        row = next(r for r in body["items"] if r["key"] == "vector_search")
        assert row["state"] != "active"          # off if installed, missing if not
        # persisted to disk (the bundled app restarts with it remembered)
        cfg = BrainConfig.load(lb.cfg_dir)
        assert cfg.disabled_caps == ["vector_search"]
        # switch it back on
        status, body = _req(lb.url + "/dreamlayer/capabilities",
                            {"key": "vector_search", "disabled": False}, lb.h)
        assert status == 200 and body["disabled"] == []
        assert BrainConfig.load(lb.cfg_dir).disabled_caps == []
    finally:
        lb.stop()


def test_toggle_rejects_unknown_key(tmp_path):
    lb = _Live(tmp_path)
    try:
        status, body = _req(lb.url + "/dreamlayer/capabilities",
                            {"key": "warp_drive", "disabled": True}, lb.h)
        assert status == 400 and "unknown" in (body or {}).get("error", "")
        assert BrainConfig.load(lb.cfg_dir).disabled_caps == []
    finally:
        lb.stop()


def test_panel_carries_the_capabilities_view(tmp_path):
    lb = _Live(tmp_path)
    try:
        req = urllib.request.Request(lb.url + "/")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=5) as r:
            html = r.read().decode()
        for marker in ("Capabilities", "caprows", "loadCaps", "toggleCap",
                       'id:"caps"'):
            assert marker in html, f"panel missing {marker!r}"
    finally:
        lb.stop()


# --- packs: curated one-click upgrades ----------------------------------------

import time

import pytest

from dreamlayer.ai_brain.server import server as _srv
from dreamlayer.capabilities import PACKS, pack_requirements


@pytest.fixture(autouse=True)
def _clean_pack_jobs():
    _srv._PACK_JOBS.clear()
    saved = _srv._PACK_RUNNER
    yield
    _srv._PACK_RUNNER = saved
    _srv._PACK_JOBS.clear()


def test_payload_includes_packs_and_gains(tmp_path):
    lb = _Live(tmp_path)
    try:
        _, body = _req(lb.url + "/dreamlayer/capabilities", headers=lb.h)
        packs = body["packs"]
        assert [p["key"] for p in packs] == [p.key for p in PACKS]
        for p in packs:
            assert {"name", "tagline", "size", "impact", "state", "caps"} <= set(p)
            assert p["state"] in ("installed", "partial", "available")
        assert sum(p["recommended"] for p in packs) == 1        # one flagship
        # every capability row explains itself: what it does + how big a gain
        for row in body["items"]:
            assert row["gain"] and 1 <= row["impact"] <= 5
    finally:
        lb.stop()


def test_pack_requirements_resolve_for_every_pack():
    for p in PACKS:
        reqs = pack_requirements(p.key)
        assert reqs, f"pack {p.key} resolved no requirements"
        assert all(isinstance(r, str) and r for r in reqs)
    assert pack_requirements("warp_drive") == []


def test_pack_install_lifecycle_with_fake_runner(tmp_path):
    calls = {}

    def fake_runner(reqs):
        calls["reqs"] = list(reqs)
        return True, "ok"

    _srv._PACK_RUNNER = fake_runner
    lb = _Live(tmp_path)
    try:
        status, body = _req(lb.url + "/dreamlayer/packs",
                            {"pack": "guardian"}, lb.h)
        assert status == 200
        for _ in range(50):                      # background thread finishes fast
            time.sleep(0.02)
            if _srv._PACK_JOBS["guardian"]["state"] == "done":
                break
        assert _srv._PACK_JOBS["guardian"]["state"] == "done"
        assert "restart the Brain" in _srv._PACK_JOBS["guardian"]["detail"]
        assert calls["reqs"] == pack_requirements("guardian")   # allowlisted set only
        # the report now carries the job so the panel can show progress
        _, body = _req(lb.url + "/dreamlayer/capabilities", headers=lb.h)
        g = next(p for p in body["packs"] if p["key"] == "guardian")
        assert g["install"]["state"] == "done"
    finally:
        lb.stop()


def test_pack_install_failure_reported(tmp_path):
    _srv._PACK_RUNNER = lambda reqs: (False, "no network")
    lb = _Live(tmp_path)
    try:
        status, _ = _req(lb.url + "/dreamlayer/packs", {"pack": "operator"}, lb.h)
        assert status == 200
        for _ in range(50):
            time.sleep(0.02)
            if _srv._PACK_JOBS["operator"]["state"] == "failed":
                break
        assert _srv._PACK_JOBS["operator"]["state"] == "failed"
        assert "no network" in _srv._PACK_JOBS["operator"]["detail"]
    finally:
        lb.stop()


def test_pack_install_rejects_unknown_and_concurrent(tmp_path):
    _srv._PACK_RUNNER = lambda reqs: (time.sleep(0.3), True) and (True, "ok")
    lb = _Live(tmp_path)
    try:
        status, body = _req(lb.url + "/dreamlayer/packs", {"pack": "nope"}, lb.h)
        assert status == 400 and "unknown pack" in body["error"]
        # start a slow install, then a second must be refused
        status, _ = _req(lb.url + "/dreamlayer/packs", {"pack": "guardian"}, lb.h)
        assert status == 200
        status, body = _req(lb.url + "/dreamlayer/packs", {"pack": "operator"}, lb.h)
        assert status == 400 and "already installing" in body["error"]
    finally:
        lb.stop()


def test_pack_install_refused_when_frozen(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", "macosx_app", raising=False)
    lb = _Live(tmp_path)
    try:
        status, body = _req(lb.url + "/dreamlayer/packs", {"pack": "recall"}, lb.h)
        assert status == 400 and "can't install into itself" in body["error"]
        # and the report tells the panel it's a bundled app
        _, rep = _req(lb.url + "/dreamlayer/capabilities", headers=lb.h)
        assert rep["frozen"] is True
    finally:
        lb.stop()


def test_panel_carries_packs_ui(tmp_path):
    lb = _Live(tmp_path)
    try:
        req = urllib.request.Request(lb.url + "/")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=5) as r:
            html = r.read().decode()
        for marker in ("packgrid", "installPack", "packNudge", "What this does"):
            assert marker in html, f"panel missing {marker!r}"
    finally:
        lb.stop()
