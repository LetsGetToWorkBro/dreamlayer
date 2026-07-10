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
        if _HAS_FW:
            try:
                self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
            except Exception as exc:
                log.error("[asr] faster-whisper load failed: %s; no-transcript fallback", exc)
                self._model = None

    def transcribe(self, audio, language: str = "en") -> str:
        """`audio` = a path or a mono 16k float numpy array. Returns text ("" if
        the dep/model is unavailable)."""
        if self._model is None:
            return ""
        try:
            segments, _info = self._model.transcribe(audio, language=language)
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception as exc:
            log.error("[asr] transcribe failed: %s", exc)
            return ""
