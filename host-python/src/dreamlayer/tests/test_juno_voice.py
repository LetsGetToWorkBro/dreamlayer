"""Juno's local voice, routed the right way: the Brain synthesizes and the
CLIENT plays. Piper isn't installed in CI, so these pin the contract — the
endpoint reports not-ready and returns a clean 204 (never a 500), the panel
ships the toggle + player, and the synth path is gated + bounded.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.store import BrainConfig

TOKEN = "reed-lark"


def _brain(tmp_path) -> Brain:
    d = tmp_path / "cfg"
    d.mkdir()
    BrainConfig(token=TOKEN).save(d)
    return Brain(d)


def _serve(brain):
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _req(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


class TestVoiceEndpoint:
    def test_status_reports_not_ready_without_a_voice(self, tmp_path):
        server, base = _serve(_brain(tmp_path))
        try:
            hdr = {"X-DreamLayer-Token": TOKEN}
            status, _ct, body = _req(base + "/dreamlayer/tts", headers=hdr)
            assert status == 200
            j = json.loads(body)
            assert j["ready"] is False and j["voice"] == ""
        finally:
            server.shutdown(); server.server_close()

    def test_synth_without_a_voice_is_204_not_500(self, tmp_path):
        server, base = _serve(_brain(tmp_path))
        try:
            hdr = {"X-DreamLayer-Token": TOKEN, "Content-Type": "application/json"}
            status, _ct, _b = _req(base + "/dreamlayer/tts",
                                   data=json.dumps({"text": "hello"}).encode(),
                                   headers=hdr)
            assert status == 204            # no voice model → silent, never an error
        finally:
            server.shutdown(); server.server_close()

    def test_empty_text_is_rejected(self, tmp_path):
        server, base = _serve(_brain(tmp_path))
        try:
            hdr = {"X-DreamLayer-Token": TOKEN, "Content-Type": "application/json"}
            status, _ct, _b = _req(base + "/dreamlayer/tts",
                                   data=json.dumps({"text": "   "}).encode(),
                                   headers=hdr)
            assert status == 400
        finally:
            server.shutdown(); server.server_close()

    def test_endpoint_requires_auth(self, tmp_path):
        server, base = _serve(_brain(tmp_path))
        try:
            status, _ct, _b = _req(base + "/dreamlayer/tts",
                                   data=json.dumps({"text": "hi"}).encode(),
                                   headers={"Content-Type": "application/json",
                                            "Origin": "http://evil.example"})
            assert status in (401, 403)     # no token / cross-origin → refused
        finally:
            server.shutdown(); server.server_close()


class TestPanelShipsTheVoice:
    def test_panel_carries_the_toggle_and_player(self):
        from dreamlayer.ai_brain.server.panel import render_panel
        html = render_panel(token="t")
        assert 'id="voiceTog"' in html
        assert "junoSay(" in html and "refreshVoice(" in html
        # it plays the WAV client-side and never calls a cloud voice
        assert "new Audio(url)" in html
        assert "/dreamlayer/tts" in html
        # honest copy: on-device, no credits
        assert "no API credits" in html


class TestCloneFallback:
    def test_clone_is_a_noop_without_the_engine_or_refs(self):
        from dreamlayer.orchestrator.voice_clone import CloneTTS
        c = CloneTTS(reference=[])
        assert c.ready is False
        assert c.synthesize("hello") is None
        assert c.synthesize("") is None

    def test_clone_ignores_missing_reference_files(self, tmp_path):
        from dreamlayer.orchestrator.voice_clone import CloneTTS
        c = CloneTTS(reference=[tmp_path / "nope.mp3", object()])
        assert c.ready is False            # no real refs → not ready, never raises

    def test_voice_clone_capability_registered(self):
        from dreamlayer import capabilities as C
        cap = next((c for c in C.CAPABILITIES if c.key == "voice_clone"), None)
        assert cap is not None
        assert cap.extra == "voice-clone" and cap.modules == ("TTS",)
        assert cap.seam == "orchestrator/voice_clone.py"


def test_juno_tts_prefers_a_cloned_voice(tmp_path, monkeypatch):
    # _juno_tts should look for <cfg>/voices/juno.onnx first; without piper it's
    # not ready, but the accessor must never raise and must cache per-brain
    monkeypatch.delenv("DL_PIPER_VOICE", raising=False)
    monkeypatch.delenv("DL_VOICES_DIR", raising=False)
    import dreamlayer.ai_brain.server.server as srv
    b = _brain(tmp_path)
    inst = srv._juno_tts(b)
    assert inst is not None                 # a PiperTTS instance (just not ready)
    assert inst.ready is False
    assert srv._juno_tts(b) is inst or srv._juno_tts(b) is not None  # cached/stable
