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


class TestItSpeaksOnEveryPiperGeneration:
    """`_raw_pcm` claims to work "across piper API generations". It did not.

    piper moved from rhasspy/piper to OHF-voice/piper1-gpl at 1.3, and
    `synthesize`'s second positional argument stopped being a wave writer and
    became a `SynthesisConfig`. Passing `wf` there does not raise — it builds a
    generator nobody iterates, so the file closes with zero frames and the
    caller reads back silence with NOTHING in the log. These fakes are shaped
    like the real classes so the wrong branch produces the real symptom
    (`b""`), not an exception a test would notice for free.
    """

    @staticmethod
    def _wav(wf, frames=b"\x01\x02" * 800):
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(frames)

    def _pcm_from(self, voice):
        tts = T.PiperTTS()
        tts._voice = voice
        return tts._raw_pcm("hello")

    def test_the_oldest_generation_streams_raw_chunks(self):
        class V:                                    # piper <=1.1
            def synthesize_stream_raw(self, text):
                yield b"\x01\x02" * 400
                yield b"\x03\x04" * 400
        assert len(self._pcm_from(V())) == 1600

    def test_the_middle_generation_writes_into_the_wave_file(self):
        outer = self

        class V:                                    # piper ==1.2
            def synthesize(self, text, wf):
                outer._wav(wf)
        assert len(self._pcm_from(V())) == 1600

    def test_the_gpl_generation_is_not_silently_empty(self, caplog):
        """The regression this whole class exists for."""
        outer = self
        misused = []

        class V:                                    # piper >=1.3
            def synthesize(self, text, syn_config=None, include_alignments=False):
                misused.append(syn_config)
                return iter(())                     # a generator, not audio
            def synthesize_wav(self, text, wf, syn_config=None,
                               set_wav_format=True, include_alignments=False):
                outer._wav(wf)

        pcm = self._pcm_from(V())
        assert pcm, "piper >=1.3 produced silence — synthesize_wav was not used"
        assert len(pcm) == 1600
        assert misused == [], (
            "a wave writer was passed where a SynthesisConfig belongs")

    def test_an_engine_that_returns_no_audio_answers_none_not_empty_bytes(self):
        """`b""` and `None` mean different things to `synthesize`, which tests
        `if not pcm` — but `play(b"")` is reached by other paths, so the
        distinction is worth keeping at the source."""
        outer = self

        class V:
            def synthesize_wav(self, text, wf, **kw):
                outer._wav(wf, frames=b"")
        assert self._pcm_from(V()) is None


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

class TestVoiceConfigParsing:
    """DL_JUNO_VOICE must read like a boolean flag: only affirmative spellings
    turn it on. The old `not in ("","0","false","no")` flipped ON for `off`,
    `False`, `No`, ` 0`… — the opposite of what an operator silencing a room
    would expect (audit fix)."""

    def _flag(self, monkeypatch, val):
        from dreamlayer.config import Config
        if val is None:
            monkeypatch.delenv("DL_JUNO_VOICE", raising=False)
        else:
            monkeypatch.setenv("DL_JUNO_VOICE", val)
        return Config().juno_voice

    def test_unset_and_negative_spellings_are_off(self, monkeypatch):
        for v in (None, "", "0", "false", "no", "off", "OFF", "False", "No", " 0 "):
            assert self._flag(monkeypatch, v) is False, f"{v!r} should be OFF"

    def test_affirmative_spellings_are_on(self, monkeypatch):
        for v in ("1", "true", "TRUE", "yes", "on", " on "):
            assert self._flag(monkeypatch, v) is True, f"{v!r} should be ON"


def test_local_tts_capability_registered():
    from dreamlayer import capabilities as C
    cap = next((c for c in C.CAPABILITIES if c.key == "local_tts"), None)
    assert cap is not None
    assert cap.extra == "voice"
    assert cap.modules == ("piper",)
    assert cap.seam == "orchestrator/tts_piper.py"
    assert cap.before == 0        # the fallback simply can't speak
