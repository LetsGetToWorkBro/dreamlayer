"""test_ai_brain_server.py — the Brain app: config, index, server, clients.

Phases 2-4 plumbing + the config layer: store round-trips, the folder index,
the Ollama backend seam, the server over real localhost HTTP (config,
folders, drag-drop upload, ask, explain, history, token gate, panel), the
phone-side remote clients + router wiring, and the opt-in cloud tier."""
from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

import pytest

from dreamlayer.ai_brain import (
    BrainRouter, RemoteKnowledgeBrain, RemoteVisionBrain, connect_brain,
    CloudKnowledgeBrain, CloudVisionBrain,
)
from dreamlayer.ai_brain.server import (
    BrainConfig, QueryHistory, FileIndex, Brain, make_brain_server,
    OllamaBackend, make_synthesizer, vision_answer,
)


def _post(url, payload, headers=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=5) as r:
            ct = r.headers.get("Content-Type", "")
            body = r.read().decode()
            return r.status, (json.loads(body) if "json" in ct else body)
    except urllib.error.HTTPError as e:
        return e.code, None


# ---------------------------------------------------------------------------
# Store + index
# ---------------------------------------------------------------------------

class TestStore:
    def test_config_round_trip_and_folders(self, tmp_path):
        c = BrainConfig()
        assert c.add_folder("/a/b") and not c.add_folder("/a/b")
        c.model = "ollama"
        c.save(tmp_path)
        back = BrainConfig.load(tmp_path)
        assert back.folders == ["/a/b"] and back.model == "ollama"

    def test_public_hides_token(self):
        c = BrainConfig(token="secret")
        assert c.public()["token"] == "set"

    def test_history_records_and_reads_newest_first(self, tmp_path):
        h = QueryHistory(tmp_path)
        h.add("q1", "a1", "laptop", ["f1"], ts=1)
        h.add("q2", "a2", "cloud", [], ts=2)
        items = h.recent(10)
        assert items[0]["query"] == "q2" and items[1]["query"] == "q1"


class TestIndex:
    def _folder(self, tmp_path):
        d = tmp_path / "notes"
        d.mkdir()
        (d / "lease.md").write_text("Rent is 2400 per month.\n\n"
                                    "The lease ends in June 2026.")
        (d / "marcus.txt").write_text("Marcus owes me the signed contract.")
        (d / "photo.jpg").write_bytes(b"\xff\xd8\xff")     # non-text: ignored
        return d

    def test_reindex_counts_text_files(self, tmp_path):
        cfg = BrainConfig(folders=[str(self._folder(tmp_path))])
        idx = FileIndex(cfg)
        stats = idx.reindex()
        assert stats["files"] == 2                 # jpg skipped

    def test_ask_returns_passage_and_source(self, tmp_path):
        cfg = BrainConfig(folders=[str(self._folder(tmp_path))])
        idx = FileIndex(cfg); idx.reindex()
        ans = idx.ask("how much is the rent")
        assert "2400" in ans.text and ans.sources == ["lease.md"]

    def test_ask_no_match(self, tmp_path):
        cfg = BrainConfig(folders=[str(self._folder(tmp_path))])
        idx = FileIndex(cfg); idx.reindex()
        assert idx.ask("airspeed of a swallow") is None

    def test_synthesizer_is_used_when_present(self, tmp_path):
        cfg = BrainConfig(folders=[str(self._folder(tmp_path))])
        idx = FileIndex(cfg, synthesizer=lambda q, ps: "SYNTHESISED")
        idx.reindex()
        assert idx.ask("rent").text == "SYNTHESISED"


class TestOllamaBackend:
    def test_chat_and_vision_via_mock_transport(self):
        posts = []
        def http_post(url, payload):
            posts.append((url, payload))
            return {"response": "a mock answer"}
        cfg = BrainConfig(model="ollama")
        b = OllamaBackend(cfg, http_post=http_post)
        assert b.chat("hi") == "a mock answer"
        assert b.vision("mug", None, "quick") == "a mock answer"
        assert posts[0][0].endswith("/api/generate")

    def test_vision_answer_none_without_backend(self):
        assert vision_answer(None, "mug", None, "quick") is None


# ---------------------------------------------------------------------------
# The server over real HTTP
# ---------------------------------------------------------------------------

class LiveBrain:
    def __init__(self, tmp_path, token="tok", folders=None):
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        c = BrainConfig(token=token, folders=folders or [])
        c.save(cfg_dir)
        self.brain = Brain(cfg_dir)
        self.server = make_brain_server(self.brain, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.h = {"X-DreamLayer-Token": token}

    def stop(self):
        self.server.shutdown(); self.server.server_close()


class TestServer:
    def test_panel_served_at_root(self, tmp_path):
        lb = LiveBrain(tmp_path)
        try:
            status, body = _get(lb.url + "/")
            assert status == 200 and "DreamLayer" in body and "Brain" in body
            # the People section now merges the glasses' social memory
            # (relation/notes/debts) with the dossier registry
            assert "/dreamlayer/social/people" in body and "met on Halo" in body
            # Juno lives on the panel: her mount + sprite script are present
            assert 'class="juno-hero"' in body and "data-juno" in body
            assert "/dreamlayer/build/juno/juno.js" in body
        finally:
            lb.stop()

    def test_juno_script_and_assets_serve(self, tmp_path):
        lb = LiveBrain(tmp_path)
        try:
            # the UMD sprite script — text, JS content-type
            status, body = _get(lb.url + "/dreamlayer/build/juno/juno.js")
            assert status == 200 and "Juno" in body and "mount" in body
            # a binary asset — raw read (can't decode as text)
            req = urllib.request.Request(lb.url + "/dreamlayer/build/juno/juno_idle.webp")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=5) as r:
                assert r.status == 200
                assert r.headers.get("Content-Type") == "image/webp"
                assert len(r.read()) > 100
            # path traversal and unknown extensions are refused
            assert _get(lb.url + "/dreamlayer/build/juno/..%2f..%2fserver.py")[0] == 404
            assert _get(lb.url + "/dreamlayer/build/juno/secrets.env")[0] == 404
        finally:
            lb.stop()

    def test_token_required_for_api(self, tmp_path):
        lb = LiveBrain(tmp_path)
        try:
            assert _get(lb.url + "/dreamlayer/config")[0] == 401   # no token
            assert _get(lb.url + "/dreamlayer/config", lb.h)[0] == 200
        finally:
            lb.stop()

    def test_add_folder_and_upload_then_ask(self, tmp_path):
        watch = tmp_path / "watched"; watch.mkdir()
        lb = LiveBrain(tmp_path)
        try:
            # add the folder via the API
            _post(lb.url + "/dreamlayer/folders",
                  {"action": "add", "path": str(watch)}, lb.h)
            # drag-drop a file into it
            up = (lb.url + "/dreamlayer/upload?folder="
                  + urllib.request.quote(str(watch)) + "&name=lease.md")
            req = urllib.request.Request(
                up, data=b"Rent is 2400 per month.", headers=lb.h)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=5) as r:
                assert json.loads(r.read())["ok"] is True
            assert (watch / "lease.md").exists()
            # now ask about it
            status, ans = _post(lb.url + "/dreamlayer/brain/ask",
                                {"query": "how much is rent"}, lb.h)
            assert status == 200 and "2400" in ans["text"]
            # and it's in history
            _, hist = _get(lb.url + "/dreamlayer/history", lb.h)
            assert hist["items"][0]["query"] == "how much is rent"
        finally:
            lb.stop()

    def test_upload_rejects_unwatched_folder(self, tmp_path):
        lb = LiveBrain(tmp_path)
        try:
            up = lb.url + "/dreamlayer/upload?folder=/etc&name=evil.txt"
            req = urllib.request.Request(up, data=b"x", headers=lb.h)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with opener.open(req, timeout=5) as r:
                    assert False, "unwatched write should be rejected"
            except urllib.error.HTTPError as e:
                assert e.code == 400 and json.loads(e.read())["ok"] is False
            assert not (Path("/etc") / "evil.txt").exists()
        finally:
            lb.stop()

    def test_explain_empty_without_vision_model(self, tmp_path):
        lb = LiveBrain(tmp_path)
        try:
            _, ans = _post(lb.url + "/dreamlayer/brain/explain",
                           {"label": "mug", "want": "quick"}, lb.h)
            assert ans["text"] == ""       # keyword model has no vision tier
        finally:
            lb.stop()


# ---------------------------------------------------------------------------
# Phone-side clients + router + cloud tier
# ---------------------------------------------------------------------------

class TestRemoteAndRouter:
    def test_remote_knowledge_through_router(self, tmp_path):
        watch = tmp_path / "w"; watch.mkdir()
        (watch / "lease.md").write_text("Rent is 2400 per month.")
        lb = LiveBrain(tmp_path, folders=[str(watch)])
        try:
            router = BrainRouter()
            connect_brain(router, lb.url, token="tok")
            ans = router.ask("how much is rent")
            assert ans is not None and "2400" in ans.text and ans.tier == "laptop"
        finally:
            lb.stop()

    def test_remote_returns_none_on_bad_token(self, tmp_path):
        lb = LiveBrain(tmp_path, folders=[])
        try:
            rk = RemoteKnowledgeBrain(lb.url, token="wrong")
            assert rk.ask("anything") is None      # 401 -> None, not a crash
        finally:
            lb.stop()


class TestCloudTier:
    def _router(self):
        r = BrainRouter()
        r.add_knowledge(CloudKnowledgeBrain(lambda q: f"cloud says: {q}"))
        r.add_vision(CloudVisionBrain(lambda f, l, w: f"cloud sees a {l}"))
        return r

    def test_cloud_gated_off_by_default(self):
        assert self._router().ask("hi") is None

    def test_cloud_answers_when_opted_in(self):
        r = self._router()
        r.opt_in_cloud(True)
        assert "cloud says" in r.ask("hi").text
        assert r.explain(None, "mug").tier == "cloud"
