"""orchestrator/tts_kokoro.py — Juno's Kokoro-82M voice (on-device).

The `kokoro` wheel + its 82M model aren't in CI, so these pin the graceful
fallback: absent the engine, KokoroTTS is not ready, synthesize() returns None,
play() is a silent no-op, and make_speak_fn() hands back a silent no-op whose
.ready is False — so the orchestrator can fall through to Piper. Also the
capability registration and the WAV shape when a fake pipeline IS injected.
"""
from __future__ import annotations

import io
import wave

import numpy as np

from dreamlayer.orchestrator import tts_kokoro as K


class TestFallback:
    def test_not_ready_without_wheel(self):
        t = K.KokoroTTS()
        assert t.ready is (K._HAS_KOKORO and t._pipe is not None)
        if not K._HAS_KOKORO:
            assert t.ready is False

    def test_synthesize_none_without_engine(self):
        t = K.KokoroTTS()
        if not t.ready:
            assert t.synthesize("hello") is None
            assert t.synthesize("") is None

    def test_play_is_silent_noop_on_empty(self):
        K.KokoroTTS().play(b"")          # must not raise

    def test_make_speak_fn_is_silent_noop_without_engine(self):
        speak = K.make_speak_fn()
        if not K._HAS_KOKORO:
            assert getattr(speak, "ready", None) is False
            assert speak("anything") is None     # no raise, no sound


class TestWithFakePipeline:
    def test_synthesize_wraps_chunks_into_wav(self):
        # inject a fake Kokoro pipeline: yields (graphemes, phonemes, audio) chunks
        t = K.KokoroTTS.__new__(K.KokoroTTS)
        t._rate = 24000
        t.voice_name = "af_heart"

        def fake_pipe(text, voice=None):
            yield ("g", "p", np.linspace(-1, 1, 240, dtype=np.float32))
            yield ("g", "p", np.linspace(1, -1, 240, dtype=np.float32))

        t._pipe = fake_pipe
        wav = t.synthesize("hello there")
        assert wav is not None and wav[:4] == b"RIFF"
        with wave.open(io.BytesIO(wav), "rb") as wf:
            assert wf.getframerate() == 24000 and wf.getnchannels() == 1
            assert wf.getnframes() == 480      # both chunks concatenated

    def test_empty_pipeline_output_is_none(self):
        t = K.KokoroTTS.__new__(K.KokoroTTS)
        t._rate = 24000
        t.voice_name = "af_heart"
        t._pipe = lambda text, voice=None: iter(())   # yields nothing
        assert t.synthesize("hello") is None


def test_kokoro_capability_registered():
    from dreamlayer import capabilities as C
    cap = {c.key: c for c in C.CAPABILITIES}.get("kokoro_tts")
    assert cap is not None, "kokoro_tts capability missing"
    assert cap.extra == "voice"
    assert "kokoro" in cap.modules
    assert cap.seam == "orchestrator/tts_kokoro.py"
