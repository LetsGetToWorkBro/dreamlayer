"""On-device voice pipeline real-path coverage (issue #422): Silero VAD
(orchestrator/vad_gate.py, ~65 lines) and faster-whisper ASR
(orchestrator/asr_faster_whisper.py, ~50 lines) each lazy-import an optional
dep (extras group `voice`) and degrade to a fallback when it's absent -- an
RMS energy threshold for VAD, an empty transcript for ASR -- and today only
that fallback runs (test_integration_seams_pr1.py::test_vad_and_asr_fallback,
against the *dep-absent* case). This adds the real-path assertions the issue
asks for: SileroVADGate.is_speech() separating genuinely speech-shaped audio
from silence, and FasterWhisperASR.transcribe() recovering a recognizable
spoken word.

Per-class importorskip in setup_method (mirrors TestRealLancePath /
TestRealChromaPersistentResidue in test_alt_vector_stores_ranking.py): the two
deps are independent, so an environment with only one of silero-vad /
faster-whisper installed still runs the half it can, and skips the other.

Fixture (voice_fixture_hello_16k.wav, ~0.74s / 23KB, mono PCM16 @ 16kHz): one
genuinely spoken word, not a hand-coded tone. This was checked empirically,
not assumed: a pure sine tone, white noise, and even a pitch-modulated
harmonic stack with a syllable-rate amplitude envelope are exactly what both
real models are trained to REJECT as non-speech -- Silero returns no
speech_timestamps for any of them, and faster-whisper transcribes all three
to "" (verified against the real tiny.en/base.en models before writing this
file). A synthesized tone/noise burst therefore cannot honestly stand in for
"the spoken words from a short WAV" that the issue asks the ASR test to pin.
The fixture word was produced once with espeak-ng (a deterministic, offline,
license-free TTS engine -- not a recording of a person, not a mock of the
pipeline under test) and resampled to 16kHz mono with ffmpeg; the committed
WAV is a static test asset, so the test file itself has no runtime TTS
dependency and no network access. VAD's "speech-shaped audio" positive case
reuses the same file -- Silero's speech_timestamps on it are non-empty too,
so one fixture honestly covers both halves of the issue.

Non-vacuity (the #396 lesson, carried from test_embedder_local_real.py /
#448): each real-path test spies on the fallback the production code would
silently use if the real branch were unreachable. Neither module keeps a
persistent mock object the way embedder_local.py's `_mock` does, so the spy
targets the actual fallback surface instead: SileroVADGate._energy (always
present on the gate regardless of _HAS_SILERO) for VAD, and the loaded
WhisperModel's own bound `.transcribe` (only reachable at all when the real
branch built it) for ASR -- proving FasterWhisperASR.transcribe() called INTO
the model rather than hitting the `self._model is None` early return.
Mutation-verified (see PR body for the verbatim run): forcing
`_HAS_SILERO`/`_HAS_FW` False while these real-path tests run makes them fail
-- the energy spy fires (VAD) / there is no model left to spy on (ASR) --
while the dedicated fallback tests below, which force the very same flags,
stay green.
"""
from __future__ import annotations

import array
import wave
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "voice_fixture_hello_16k.wav"


def _read_wav_samples(path: Path) -> list[float]:
    """Stdlib-only mono PCM16 WAV reader -> a plain list of floats in
    [-1, 1]. No numpy import here: this helper runs regardless of which
    optional voice dep (if any) is installed."""
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        raw = w.readframes(w.getnframes())
    ints = array.array("h")
    ints.frombytes(raw)
    return [v / 32768.0 for v in ints]


class TestRealVADPath:
    def setup_method(self):
        pytest.importorskip("silero_vad")

    def _real_gate(self):
        # No skip-on-None guard here (unlike #417/#448's "weights could not
        # load" escape hatch): silero-vad ships its weights INSIDE the pip
        # package (no network fetch), so once the import above didn't skip,
        # construction should always succeed. Skipping on `_model is None`
        # would also silently swallow the mutation this file is required to
        # catch (_HAS_SILERO forced False) -- the whole point of the test.
        from dreamlayer.orchestrator.vad_gate import SileroVADGate
        return SileroVADGate()

    def _energy_spy(self, gate, monkeypatch):
        calls = []
        real = gate._energy

        def spy(*a, **k):
            calls.append((a, k))
            return real(*a, **k)

        monkeypatch.setattr(gate, "_energy", spy)
        return calls

    @pytest.mark.real_model
    def test_speech_shaped_audio_is_detected(self, monkeypatch):
        gate = self._real_gate()
        energy_calls = self._energy_spy(gate, monkeypatch)
        samples = _read_wav_samples(FIXTURE)
        assert gate.is_speech(samples) is True
        assert energy_calls == []          # real Silero path answered, not RMS

    @pytest.mark.real_model
    def test_silence_is_not_detected(self, monkeypatch):
        gate = self._real_gate()
        energy_calls = self._energy_spy(gate, monkeypatch)
        silence = [0.0] * 16000            # 1s of true digital silence
        assert gate.is_speech(silence) is False
        assert energy_calls == []          # real Silero path answered, not RMS


class TestVADFallback:
    def test_forced_unavailable_uses_energy_heuristic(self, monkeypatch):
        # Force the "silero-vad not installed" branch even though the
        # package IS installed in this environment (it must be, to reach
        # TestRealVADPath above): proves the _HAS_SILERO guard degrades
        # cleanly to the RMS heuristic on its own.
        from dreamlayer.orchestrator import vad_gate
        monkeypatch.setattr(vad_gate, "_HAS_SILERO", False)
        gate = vad_gate.SileroVADGate(threshold=0.05)
        assert gate._model is None
        assert gate.is_speech([0.5, -0.6, 0.55, -0.5] * 40) is True    # loud
        assert gate.is_speech([0.0, 0.001, -0.001] * 40) is False      # quiet


class TestRealASRPath:
    def setup_method(self):
        pytest.importorskip("faster_whisper")

    def _real_asr(self):
        # No skip-on-None guard here either (see TestRealVADPath._real_gate):
        # `_HAS_FW` gates the ONLY way `_model` can end up None once the
        # import above didn't skip, and swallowing that into a skip would
        # also swallow the required `_HAS_FW`-forced mutation.
        from dreamlayer.orchestrator.asr_faster_whisper import FasterWhisperASR
        return FasterWhisperASR()

    def _model_spy(self, asr, monkeypatch):
        """Spy on the loaded WhisperModel's own bound .transcribe -- the
        only way to prove FasterWhisperASR.transcribe() called into the real
        model rather than short-circuiting on `self._model is None`."""
        assert asr._model is not None, "expected the real WhisperModel to be loaded"
        calls = []
        real = asr._model.transcribe

        def spy(*a, **k):
            calls.append((a, k))
            return real(*a, **k)

        monkeypatch.setattr(asr._model, "transcribe", spy)
        return calls

    @pytest.mark.real_model
    def test_transcribes_the_spoken_word(self, monkeypatch):
        import numpy as np
        asr = self._real_asr()
        calls = self._model_spy(asr, monkeypatch)
        samples = np.array(_read_wav_samples(FIXTURE), dtype="float32")
        text = asr.transcribe(samples)
        assert len(calls) == 1                 # the real model actually ran
        assert text != ""
        assert "hello" in text.lower()          # the recognizable spoken word


class TestASRFallback:
    def test_forced_unavailable_returns_empty_without_raising(self, monkeypatch):
        # Force the "faster-whisper not installed" branch even though the
        # package IS installed in this environment (it must be, to reach
        # TestRealASRPath above): proves the _HAS_FW guard degrades cleanly
        # on its own, matching the no-dep contract callers already rely on.
        from dreamlayer.orchestrator import asr_faster_whisper
        monkeypatch.setattr(asr_faster_whisper, "_HAS_FW", False)
        asr = asr_faster_whisper.FasterWhisperASR()
        assert asr._model is None
        assert asr.transcribe("nonexistent.wav") == ""     # must not raise
