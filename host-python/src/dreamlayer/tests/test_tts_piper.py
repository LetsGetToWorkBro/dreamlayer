"""Piper TTS adapter + the orchestrator's _juno_say voice seam.

The engine itself isn't installed in CI, so these pin the CONTRACT that matters:
absent piper/voice/device is a silent no-op (never a crash), the model finder is
honest about what counts as a usable voice, and every Juno reply still ships its
text card whether or not she can speak.
"""
from __future__ import annotations

from dreamlayer.orchestrator import tts_piper as T
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


# --- the adapter, with the dep absent (the CI reality) -----------------------

class TestAdapterFallback:
    def test_synthesize_is_none_without_a_voice(self):
        # no piper OR no model → not ready → synthesize returns None, never raises
        tts = T.PiperTTS()
        assert tts.ready is False
        assert tts.synthesize("hello") is None
        assert tts.synthesize("") is None

    def test_play_swallows_empty_and_bad_bytes(self):
        tts = T.PiperTTS()
        tts.play(b"")            # no-op
        tts.play(b"not a wav")   # decode error is swallowed, not raised

    def test_make_speak_fn_returns_a_noop_callable_when_unavailable(self):
        speak = T.make_speak_fn()
        assert callable(speak)
        assert speak("anything") is None      # silent, never raises


class TestVoiceModelFinder:
    def test_none_when_nothing_matches(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DL_PIPER_VOICE", raising=False)
        monkeypatch.delenv("DL_VOICES_DIR", raising=False)
        assert T.find_voice_model(dirs=(tmp_path,)) is None

    def test_needs_the_json_sibling(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DL_PIPER_VOICE", raising=False)
        monkeypatch.delenv("DL_VOICES_DIR", raising=False)
        lonely = tmp_path / "en_US-amy.onnx"
        lonely.write_bytes(b"x")               # model without its config → unusable
        assert T.find_voice_model(dirs=(tmp_path,)) is None
        (tmp_path / "en_US-amy.onnx.json").write_text("{}")
        assert T.find_voice_model(dirs=(tmp_path,)) == lonely

    def test_env_voices_dir_is_searched(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DL_PIPER_VOICE", raising=False)
        (tmp_path / "v.onnx").write_bytes(b"x")
        (tmp_path / "v.onnx.json").write_text("{}")
        monkeypatch.setenv("DL_VOICES_DIR", str(tmp_path))
        assert T.find_voice_model() == tmp_path / "v.onnx"

    def test_explicit_path_wins(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DL_VOICES_DIR", raising=False)
        m = tmp_path / "chosen.onnx"
        m.write_bytes(b"x")
        (tmp_path / "chosen.onnx.json").write_text("{}")
        assert T.find_voice_model(explicit=str(m)) == m


# --- the orchestrator seam: every reply routes through _juno_say -------------

class TestJunoSaySeam:
    def _orc(self, monkeypatch):
        monkeypatch.setenv("DL_JUNO_VOICE", "0")   # keep the build silent
        return Orchestrator(FakeBridge())

    def test_juno_say_ships_the_card_and_calls_speak(self, monkeypatch):
        orc = self._orc(monkeypatch)
        spoken = []
        orc._juno_speak = spoken.append
        orc._juno_say("good morning", "answer")
        cards = [r for r in orc.bridge.raw if r.get("t") == "card"]
        assert cards, "the text card must always ship"
        assert spoken == ["good morning"]

    def test_a_crashing_speak_never_breaks_the_reply(self, monkeypatch):
        orc = self._orc(monkeypatch)
        def boom(_line):
            raise RuntimeError("audio device on fire")
        orc._juno_speak = boom
        orc._juno_say("stay calm", "answer")       # must not raise
        assert [r for r in orc.bridge.raw if r.get("t") == "card"]

    def test_set_voice_off_is_a_silent_noop(self, monkeypatch):
        orc = self._orc(monkeypatch)
        assert orc.set_voice(False) is False
        assert orc._juno_speak("x") is None

    def test_set_voice_on_without_piper_reports_false_not_crash(self, monkeypatch):
        orc = self._orc(monkeypatch)
        # piper isn't installed in CI → can't actually speak, but wiring is safe
        assert orc.set_voice(True) is False

    def test_ask_juno_speaks_its_reply(self, monkeypatch):
        orc = self._orc(monkeypatch)
        spoken = []
        orc._juno_speak = spoken.append
        out = orc.ask_juno("go incognito")          # a device command → a reply line
        assert spoken and spoken[-1] == out["text"]


# --- capability registration --------------------------------------------------

def test_local_tts_capability_registered():
    from dreamlayer import capabilities as C
    cap = next((c for c in C.CAPABILITIES if c.key == "local_tts"), None)
    assert cap is not None
    assert cap.extra == "voice"
    assert cap.modules == ("piper",)
    assert cap.seam == "orchestrator/tts_piper.py"
    assert cap.before == 0        # the fallback simply can't speak
