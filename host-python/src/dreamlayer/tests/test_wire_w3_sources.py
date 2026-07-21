"""W3 + W5 — the Brain's memory ingest, graph recall, and LAN-service config.

The parts shipped in the big-wins batch (LightRAG graph recall, the local
memory sources, the config surface); nothing drove them. These tests pin the
wiring SourceOps adds: the graph is consulted BEFORE the keyword tier, enabled
local sources fold into the index (and the graph), the sync is master-switched,
and the LAN-service credentials are masked on the way out and un-clobberable on
the way back in.

Offline by construction: no wheel, no source app, no LAN service — every path is
config-gated and []-on-absence, so the Brain answers exactly as before.
"""
from __future__ import annotations

from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.schema import Answer


# ---- graph recall consulted before the keyword tier ----------------------

class _FakeGraph:
    def __init__(self, ans):
        self.ans = ans
        self.indexed = []

    def answer(self, q):
        return self.ans

    def index(self, text):
        self.indexed.append(text)
        return True


def test_graph_absent_returns_none(tmp_path):
    b = Brain(tmp_path)
    assert b.graph_answer("what did the doctor say in March") is None


def test_ask_consults_graph_before_keyword(tmp_path):
    b = Brain(tmp_path)
    b._graph = _FakeGraph("Your knee was improving, per Dr. Lee in March.")
    b._graph_built = True
    ans = b.ask("what did the doctor say about my knee")
    assert isinstance(ans, Answer)
    assert ans.sources == ["memory-graph"]
    assert "knee" in ans.text.lower()
    assert ans.tier == "laptop"


def test_ask_falls_through_when_graph_empty(tmp_path):
    b = Brain(tmp_path)
    b._graph = _FakeGraph("")          # graph has nothing → keyword index answers
    b._graph_built = True
    # no docs indexed → keyword index returns None → ans stays None (not a crash)
    assert b.ask("obscure question with no match") is None


def test_wire_model_rearms_graph(tmp_path):
    b = Brain(tmp_path)
    b._graph = _FakeGraph("x")
    b._graph_built = True
    b._wire_model()
    assert b._graph is None and b._graph_built is False


# ---- local sources fold into the index (and the graph) -------------------

def test_collect_source_docs_empty_without_apps(tmp_path):
    b = Brain(tmp_path)
    assert b.collect_source_docs() == []


def test_sync_sources_folds_docs_into_index_and_graph(tmp_path, monkeypatch):
    b = Brain(tmp_path)
    docs = [("desk", "Working in Xcode — server.py"),
            ("screen:audio", "standup notes")]
    monkeypatch.setattr(b, "collect_source_docs", lambda: docs)
    graph = _FakeGraph("x")
    b._graph = graph
    b._graph_built = True
    added = {"n": 0}
    real_add = b.index.add_documents
    monkeypatch.setattr(b.index, "add_documents",
                        lambda d: added.__setitem__("n", len(d)) or real_add(d))
    out = b.sync_sources()
    assert out["docs"] == 2
    assert added["n"] == 2
    assert len(graph.indexed) == 2          # each doc also folded into the graph
    assert b.last_sources_sync > 0


def test_maybe_sync_gated_by_master_switch(tmp_path, monkeypatch):
    b = Brain(tmp_path)
    monkeypatch.setattr(b, "collect_source_docs", lambda: [("desk", "x")])
    # off by default → no sync
    assert b.maybe_sync_sources() == {"docs": 0, "sources": False}
    b.config.sources_sync = True
    assert b.maybe_sync_sources()["docs"] == 1


def test_immich_docs_gated_by_config(tmp_path, monkeypatch):
    b = Brain(tmp_path)
    # no base_url → skipped entirely (no import, no call)
    assert b._immich_docs() == []

    class _Immich:
        def memories(self, limit=20):
            return [{"title": "On this day, 2019", "ts": 1.0, "count": 3}]
    import dreamlayer.memory.source_immich as im
    monkeypatch.setattr(im, "default_immich", lambda base, key="": _Immich())
    b.config.immich_base_url = "http://192.168.1.5:2283"
    docs = b._immich_docs()
    assert docs == [("photo-memory", "On this day, 2019")]


def test_broken_source_is_swallowed_at_the_method_boundary(tmp_path, monkeypatch):
    # each source method self-guards, so a genuinely broken default source
    # returns [] (recorded to health) rather than raising into collect().
    b = Brain(tmp_path)
    import dreamlayer.memory.source_screenpipe as sp
    monkeypatch.setattr(sp, "default_screen_source",
                        lambda: (_ for _ in ()).throw(OSError("db locked")))
    assert b._screen_docs() == []
    assert b.collect_source_docs() == []       # the whole batch survives


# ---- W5: the LAN-service config surface ----------------------------------

def test_config_fields_present_and_default_off(tmp_path):
    b = Brain(tmp_path)
    assert b.config.sources_sync is False
    assert b.config.immich_base_url == ""
    assert b.config.home_assistant_url == ""
    assert b.config.dawarich_url == ""


def test_apply_config_sets_lan_service_fields(tmp_path):
    b = Brain(tmp_path)
    b.apply_config({"sources_sync": True,
                    "immich_base_url": "http://192.168.1.5:2283",
                    "dawarich_url": "http://192.168.1.9:3000"})
    assert b.config.sources_sync is True
    assert b.config.immich_base_url.endswith(":2283")
    assert b.config.dawarich_url.endswith(":3000")


def test_secrets_masked_in_public(tmp_path):
    b = Brain(tmp_path)
    b.apply_config({"immich_api_key": "abc", "dawarich_api_key": "def",
                    "home_assistant_token": "ghi"})
    pub = b.config.public()
    assert pub["immich_api_key"] == "set"
    assert pub["dawarich_api_key"] == "set"
    assert pub["home_assistant_token"] == "set"


def test_masked_secret_roundtrip_does_not_clobber(tmp_path):
    b = Brain(tmp_path)
    b.apply_config({"immich_api_key": "realkey"})
    # the panel round-trips the "set" mask for an unchanged secret
    b.apply_config({"immich_api_key": "set"})
    assert b.config.immich_api_key == "realkey"
    # a genuine change still lands
    b.apply_config({"immich_api_key": "newkey"})
    assert b.config.immich_api_key == "newkey"


def test_source_sync_loop_start_stop(tmp_path):
    b = Brain(tmp_path)
    b.start_source_sync(interval=60.0)
    assert b._src_stop is not None
    b.start_source_sync(interval=60.0)      # idempotent
    b.stop_source_sync()
    assert b._src_stop is None
