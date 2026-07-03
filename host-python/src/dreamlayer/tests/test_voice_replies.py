"""test_voice_replies.py — voice intent routing + smart replies."""
from __future__ import annotations

import json
import threading
import urllib.request

from dreamlayer.orchestrator.voice import parse_intent, strip_wake
from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.store import BrainConfig


def _op():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


class TestVoiceGrammar:
    def test_wake_stripped(self):
        assert strip_wake("Hey DreamLayer, brief me") == "brief me"
        assert strip_wake("what did I miss") == "what did I miss"

    def test_reply_intent(self):
        it = parse_intent("reply to Priya saying on my way")
        assert it.kind == "reply" and it.args == {"to": "Priya", "text": "on my way"}
        assert parse_intent("text Marcus with running late").args["to"] == "Marcus"

    def test_locate_intent(self):
        assert parse_intent("where did I leave my bike?").kind == "locate"
        assert parse_intent("where's my keys").args["subject"] == "keys"

    def test_recall_and_brief_and_missed(self):
        assert parse_intent("Hey DreamLayer, what did Marcus need?").kind == "recall"
        assert parse_intent("brief me").kind == "brief"
        assert parse_intent("what did I miss?").kind == "missed"

    def test_fallback_is_ask(self):
        it = parse_intent("how tall is the Eiffel tower")
        assert it.kind == "ask" and "eiffel" in it.args["query"].lower()


class TestHandleVoice:
    def _orc(self):
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        from dreamlayer.ai_brain import BrainRouter, MockKnowledgeBrain
        orc = Orchestrator(FakeBridge())
        orc.brain = BrainRouter(cloud_opt_in=False, local_only=True)
        orc.brain.add_knowledge(MockKnowledgeBrain({"rent": "Rent is 2400 a month."}))
        return orc

    def test_recall_routes_to_the_brain(self):
        orc = self._orc()
        r = orc.handle_voice("Hey DreamLayer, what does the rent need?")
        assert r["intent"] == "recall" and "2400" in r["answer"]

    def test_reply_comes_back_structured(self):
        orc = self._orc()
        r = orc.handle_voice("reply to Priya saying almost there")
        assert r == {"intent": "reply", "to": "Priya", "text": "almost there"}


class TestSmartReplies:
    def test_replies_fallback_without_model(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="t").save(cfg)
        brain = Brain(cfg)
        srv = make_brain_server(brain, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            req = urllib.request.Request(
                url + "/dreamlayer/replies", data=json.dumps({"text": "you around?"}).encode(),
                headers={"X-DreamLayer-Token": "t", "Content-Type": "application/json"})
            r = json.loads(_op().open(req, timeout=5).read())
            assert len(r["replies"]) == 3 and all(isinstance(x, str) for x in r["replies"])
        finally:
            srv.shutdown(); srv.server_close()
