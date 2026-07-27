"""faster-whisper on-device ASR — turn an audio window into text.

ADD-alongside: new module. The host has no capture path today, so this is the
provider a future capture/bridge layer calls to produce the `transcript` that
voice.parse_intent() / orchestrator.handle_voice() already consume. Lazy-imports
faster-whisper (extras group `voice`); when absent, transcribe() returns "" so
callers behave exactly as they do today (no transcript = no-op).
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.asr_faster_whisper")

try:  # optional dep — extras group `voice`
    from faster_whisper import WhisperModel  # type: ignore
    _HAS_FW = True
except ImportError:
    _HAS_FW = False


# Per-profile model choices. tiny.en is a battery choice, not a quality
# choice: Name Capture, spoken commitments, and Veritas all die at the WER a
# glasses-frame mic gives tiny.en (~15-25% in the wild). base.en is the
# floor; the Mac Brain can afford small.en. Front with the silero-VAD gate
# (vad_gate.py) so ASR runs on speech, not on silence.
PROFILE_MODELS = {
    "phone": "base.en",       # pocket hub: quality floor, VAD-gated
    "mac":   "small.en",      # the Brain: accuracy over battery
    "min":   "tiny.en",       # explicit low-power opt-in only
}
DEFAULT_MODEL = PROFILE_MODELS["phone"]


class FasterWhisperASR:
    available = _HAS_FW

    def __init__(self, model_size: str = DEFAULT_MODEL, device: str = "auto", compute_type: str = "int8"):
        self._model = None
        self.last_error: Exception | None = None
        if _HAS_FW:
            try:
                self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
            except Exception as exc:
                log.error("[asr] faster-whisper load failed: %s; no-transcript fallback", exc)
                self._model = None

    def transcribe(self, audio, language: str = "en",
                   sample_rate: int = 16000) -> str:
        """`audio` = a path, OR any array-like of PCM samples (list, int16
        array, stereo — whatever the mic hands over). Returns text ("" if the
        dep/model is unavailable).

        The coercion is not a nicety. ``CapturePipeline._endpoint`` accumulates
        into a plain Python ``list`` (``SoundDeviceMic.read``/``RemoteMicSource
        .read`` both return lists) and hands that straight here. faster-whisper
        does ``if not isinstance(audio, np.ndarray): audio = decode_audio(audio)``
        → ``av.open(list)`` → ``ValueError: File object has no read() method``,
        which this method swallowed into a log line — so the always-on ear
        transcribed *nothing* on the faster-whisper rung (the rung a plain
        ``pip install dreamlayer[voice]`` lands on) while every status surface
        reported the engine live. Moonshine's twin coerced all along; only this
        one did not, under a shared docstring claiming both did.

        A `str`/path is passed through untouched so the documented file-path form
        still works, and a failure still returns "" (callers rely on "no
        transcript = no-op" and must not see an exception from a bad path) — but
        it is recorded on ``last_error`` so ``CapturePipeline`` can put it on the
        health ledger. Silence that merely *looks* like silence is how the
        original bug hid for a whole release."""
        if self._model is None:
            return ""
        self.last_error = None
        try:
            if not isinstance(audio, (str, bytes)) and not hasattr(audio, "__fspath__"):
                from .sound_events import _to_mono
                mono = _to_mono(audio, sample_rate, 16000)
                if mono is None:
                    return ""
                audio = mono
            segments, _info = self._model.transcribe(audio, language=language)
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception as exc:
            log.error("[asr] transcribe failed: %s", exc)
            self.last_error = exc
            return ""
