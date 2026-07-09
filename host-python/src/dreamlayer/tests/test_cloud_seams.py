"""DreamLayer Cloud client seams (docs/CLOUD.md): plan entitlements stay
union-only, the managed-AI preset speaks proper OpenAI wire, the waitlist
reference API works (the Worker mirrors it), the relay transport buffers
through outages without touching mesh crypto, and sync blobs are provably
secret-free and ciphertext-only."""
from __future__ import annotations

import json

import pytest

from dreamlayer.ai_brain.server import Brain, BrainConfig
from dreamlayer.ai_brain.server.server import PLAN_CAPS, PLAN_CAP_INFO
from dreamlayer.ai_brain.server.backends import PROVIDER_PRESETS, _build_cloud_request
from dreamlayer.ai_brain.server import cloud_sync
from dreamlayer.confluence.relay_transport import CloudRelayTransport
from dreamlayer.plugins.social import SocialStore, route


# --- plan entitlements ---------------------------------------------------------

def _brain(tmp_path, plan="free"):
    cfg = tmp_path / f"cfg-{plan}"
    cfg.mkdir()
    BrainConfig(plan=plan).save(cfg)
    return Brain(cfg)


def test_cloud_plan_is_union_only(tmp_path):
    free = _brain(tmp_path, "free").plugin_capabilities()
    cloud = _brain(tmp_path, "cloud").plugin_capabilities()
    assert PLAN_CAPS["cloud"] == {"cloud_ai", "cloud_sync", "cloud_relay"}
    assert free <= cloud                          # cloud only ever ADDS
    assert cloud - free == PLAN_CAPS["cloud"]
    # unknown plan degrades to the free set, never crashes
    weird = _brain(tmp_path, "enterprise-maximum").plugin_capabilities()
    assert weird == free


def test_plan_summary_shapes_the_panel(tmp_path):
    s = _brain(tmp_path, "free").plan_summary()
    assert s["plan"] == "free"
    assert [c["key"] for c in s["cloud_caps"]] == sorted(PLAN_CAPS["cloud"])
    assert all(not c["active"] and c["info"] == PLAN_CAP_INFO[c["key"]]
               for c in s["cloud_caps"])
    s2 = _brain(tmp_path, "cloud").plan_summary()
    assert s2["plan"] == "cloud" and all(c["active"] for c in s2["cloud_caps"])
    # nonsense plan reports as free
    assert _brain(tmp_path, "abc").plan_summary()["plan"] == "free"


# --- managed-AI provider preset --------------------------------------------------

def test_dreamlayer_preset_builds_openai_wire():
    p = PROVIDER_PRESETS["dreamlayer"]
    assert p["wire"] == "openai" and p["needs_key"] is True
    assert p["base_url"] == "https://api.dreamlayer.app"

    class Cfg:
        cloud_provider = "dreamlayer"
        cloud_base_url = p["base_url"]
        cloud_model = p["model"]
        cloud_api_key = "account-token-123"
    wire, url, body, headers = _build_cloud_request(Cfg(), "hello")
    assert wire == "openai"
    assert url == "https://api.dreamlayer.app/v1/chat/completions"
    assert headers["Authorization"] == "Bearer account-token-123"
    assert body["model"] == p["model"]


# --- waitlist (tested reference; the Worker mirrors this contract) ----------------

def test_waitlist_join_dedupe_and_count(tmp_path):
    store = SocialStore(str(tmp_path / "social.json"))
    st, r = route(store, "POST", "/api/waitlist", {"email": "A@Example.com "}, ts=1.0)
    assert st == 200 and r == {"joined": True, "already": False, "count": 1}
    st, r = route(store, "POST", "/api/waitlist", {"email": "a@example.com"})
    assert st == 200 and r["already"] is True and r["count"] == 1
    st, r = route(store, "GET", "/api/waitlist")
    assert st == 200 and r == {"count": 1}
    # junk rejected
    for junk in ("", "nope", "a @b.co", "@x.com", "x@"):
        st, _ = route(store, "POST", "/api/waitlist", {"email": junk})
        assert st == 400, junk
    # persisted across reload
    again = SocialStore(str(tmp_path / "social.json"))
    assert again.waitlist_count() == 1
    # and the plugins routes are untouched
    st, _ = route(store, "GET", "/api/plugins")
    assert st == 200


# --- relay transport ---------------------------------------------------------------

class _FakeRelay:
    """In-memory stand-in for the Worker's relay room."""
    def __init__(self, fail=False):
        self.packets, self.fail = [], fail

    def __call__(self, method, url, payload):
        if self.fail:
            raise OSError("relay unreachable")
        if method == "POST":
            self.packets.append(payload["wire"])
            return {"ok": True}
        since = int(url.split("since=")[1].split("&")[0])
        return {"cursor": len(self.packets), "packets": self.packets[since:]}


def test_relay_roundtrip_and_cursor():
    relay = _FakeRelay()
    a = CloudRelayTransport("room1", "alice", http=relay)
    b = CloudRelayTransport("room1", "bob", http=relay)
    a.send({"group_id": "g", "sender": "alice", "seq": 1, "kind": "weather",
            "body": {"state": "calm"}, "mac": "aa"})
    got = b.recv()
    assert len(got) == 1 and got[0]["kind"] == "weather"
    assert b.recv() == []                      # cursor advanced, no replay
    a.send({"group_id": "g", "sender": "alice", "seq": 2, "kind": "gesture",
            "body": {"sym": "ping"}, "mac": "bb"})
    assert [w["seq"] for w in b.recv()] == [2]


def test_relay_buffers_through_outage_then_flushes():
    relay = _FakeRelay(fail=True)
    t = CloudRelayTransport("room1", "alice", http=relay)
    t.send({"seq": 1}); t.send({"seq": 2})
    assert t.online is False and len(relay.packets) == 0
    relay.fail = False                          # link comes back
    t.send({"seq": 3})                          # flush drains the buffer in order
    assert [w["seq"] for w in relay.packets] == [1, 2, 3]
    assert t.online is True


# --- sync blobs ---------------------------------------------------------------------

def test_strip_secrets_removes_exactly_the_secret_fields(tmp_path):
    brain = _brain(tmp_path)
    brain.config.token = "supersecret"
    brain.config.cloud_api_key = "sk-hidden"
    snap = cloud_sync.strip_secrets(brain.export_backup())
    assert "token" not in snap["config"] and "cloud_api_key" not in snap["config"]
    assert "supersecret" not in json.dumps(snap) and "sk-hidden" not in json.dumps(snap)
    # non-secret config survives
    assert snap["config"]["plan"] == "free"


@pytest.mark.skipif(not cloud_sync.available, reason="cryptography not usable here")
def test_sync_blob_roundtrip_is_ciphertext():
    class _B:
        def export_backup(self):
            return {"version": 1, "config": {"plan": "free", "token": "t",
                                             "cloud_api_key": "k"}, "history": []}
    blob = cloud_sync.prepare_sync_blob(_B(), "correct horse battery")
    assert b"plan" not in blob and b"token" not in blob      # ciphertext, not JSON
    snap = cloud_sync.open_sync_blob(blob, "correct horse battery")
    assert snap["config"]["plan"] == "free" and "token" not in snap["config"]
    assert cloud_sync.open_sync_blob(blob, "wrong passphrase") is None
    assert cloud_sync.open_sync_blob(b"garbage", "correct horse battery") is None


def test_sync_refuses_rather_than_degrading(tmp_path, monkeypatch):
    # with no cryptography, sync must refuse loudly — plaintext is not a fallback
    monkeypatch.setattr(cloud_sync, "_HAS_FERNET", False)
    with pytest.raises(cloud_sync.SyncUnavailable):
        cloud_sync.prepare_sync_blob(_brain(tmp_path), "correct horse battery")
    with pytest.raises(cloud_sync.SyncUnavailable):
        cloud_sync.open_sync_blob(b"x", "correct horse battery")


def test_sync_rejects_weak_passphrase(tmp_path):
    if not cloud_sync.available:
        pytest.skip("cryptography not usable here")
    with pytest.raises(ValueError):
        cloud_sync.prepare_sync_blob(_brain(tmp_path), "short")
