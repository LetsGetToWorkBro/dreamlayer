"""rosetta_seamless.py — the live SeamlessM4T interpreter (ear half of Rosetta).

The model (transformers + torch + the SeamlessM4T-v2 weights) isn't in CI, so
these pin the graceful-fallback contract, the audio coercion/resample math (pure
numpy, testable), the 2→3-letter language mapping, and the RosettaLens.hear()
seam with an injected interpreter.
"""
from __future__ import annotations

import numpy as np

from dreamlayer import rosetta_seamless as RS
from dreamlayer.rosetta import RosettaLens


class TestLangMap:
    def test_two_to_three_letter(self):
        assert RS._lang3("ja") == "jpn"
        assert RS._lang3("en") == "eng"
        assert RS._lang3("zh") == "cmn"

    def test_unknown_falls_back_to_english(self):
        assert RS._lang3("xx") == "eng"
        assert RS._lang3("") == "eng"
        assert RS._lang3(None) == "eng"          # type: ignore[arg-type]


class TestAudioCoercion:
    def test_stereo_to_mono_and_resample(self):
        # 8 kHz stereo → 16 kHz mono; length should roughly double
        stereo = np.zeros((80, 2), dtype=np.float32)
        stereo[:, 0] = np.linspace(-0.5, 0.5, 80)
        out = RS._to_mono16k(stereo, 8000)
        assert out is not None and out.ndim == 1
        assert abs(out.size - 160) <= 1          # ~2x upsample
        assert float(out.max()) <= 1.0 and float(out.min()) >= -1.0

    def test_int16_scale_is_normalised(self):
        pcm = np.array([16384, -16384, 32767, -32768], dtype=np.float32)
        out = RS._to_mono16k(pcm, 16000)
        assert out is not None and float(np.max(np.abs(out))) <= 1.0

    def test_empty_audio_is_none(self):
        assert RS._to_mono16k(np.zeros(0, np.float32), 16000) is None

    def test_wav_roundtrips(self):
        wav = RS._wav_bytes(np.linspace(-1, 1, 320, dtype=np.float32), 16000)
        assert wav is not None and wav[:4] == b"RIFF"


class TestFallbacks:
    def test_interpreter_to_text_is_empty_without_wheel(self):
        it = RS.SeamlessInterpreter()
        # ready reflects whether the (absent) model loaded; in CI it's False
        assert it.to_text(np.zeros(1600, np.float32), 16000, "en") == ""

    def test_interpreter_to_speech_is_none_without_wheel(self):
        it = RS.SeamlessInterpreter()
        assert it.to_speech("hello", "jpn") is None
        assert it.to_speech("", "jpn") is None

    def test_make_interpret_fn_returns_empty_string(self):
        hear = RS.make_interpret_fn()
        assert hear(np.zeros(1600, np.float32), 16000, "en") == ""
        assert hasattr(hear, "ready")

    def test_default_interpreter_none_without_wheel(self):
        assert RS.default_interpreter() is None


class TestRosettaHearSeam:
    def test_no_interpreter_is_a_clean_noop(self):
        r = RosettaLens()                        # no interpret_fn
        res = r.hear(np.zeros(1600, np.float32), 16000, "en")
        assert res.translated == "" and res.engine == "none"

    def test_injected_interpreter_carries_meaning(self):
        r = RosettaLens(interpret_fn=lambda a, sr, t: "the kettle is boiling",
                        engine="ear")
        res = r.hear(np.zeros(1600, np.float32), 16000, "en")
        assert res.translated == "the kettle is boiling"
        assert res.source_text == ""             # we carry meaning, not transcript
        assert res.target_lang == "en" and res.engine == "ear"

    def test_a_raising_interpreter_degrades_not_crashes(self):
        def boom(a, sr, t):
            raise RuntimeError("model down")
        r = RosettaLens(interpret_fn=boom)
        res = r.hear(np.zeros(1600, np.float32), 16000, "en")
        assert res.translated == "" and res.engine == "error"

    def test_empty_interpretation_is_engine_none(self):
        r = RosettaLens(interpret_fn=lambda a, sr, t: "   ", engine="ear")
        res = r.hear(np.zeros(1600, np.float32), 16000, "en")
        assert res.translated == "" and res.engine == "none"


def test_live_interpret_capability_registered():
    from dreamlayer import capabilities as C
    cap = {c.key: c for c in C.CAPABILITIES}.get("live_interpret")
    assert cap is not None, "live_interpret capability missing"
    assert cap.extra == "interpreter"
    assert "transformers" in cap.modules
    assert cap.seam == "rosetta_seamless.py"
