"""whisperX prosody helper — word-level timestamps + per-speaker attribution to
sharpen the Truth Lens prosody channel.

ADD-alongside: new sibling to prosody.py (untouched). Lazy-imports whisperx
(extras group `voice`/`asr-extra`); when absent, `word_timings()` returns [] so
callers keep using the existing FFT-based ProsodyAnalyzer with no change.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.prosody_whisperx")

try:
    import whisperx  # type: ignore
    _HAS_WHISPERX = True
except ImportError:
    _HAS_WHISPERX = False


class WhisperXProsody:
    available = _HAS_WHISPERX

    def __init__(self, device: str = "cpu"):
        self.device = device

    def word_timings(self, audio_path: str, language: str = "en") -> list[dict]:
        """Return [{word, start, end, speaker?}] or [] when whisperx is absent."""
        if not _HAS_WHISPERX:
            return []
        try:
            model = whisperx.load_model("small", self.device, compute_type="int8")
            result = model.transcribe(audio_path, language=language)
            words = []
            for seg in result.get("segments", []):
                for w in seg.get("words", []):
                    words.append({"word": w.get("word", ""), "start": w.get("start"),
                                  "end": w.get("end"), "speaker": seg.get("speaker")})
            return words
        except Exception as exc:
            log.error("[prosody_whisperx] failed: %s", exc)
            return []
