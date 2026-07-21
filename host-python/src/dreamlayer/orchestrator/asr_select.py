"""orchestrator/asr_select.py — pick the best installed ASR engine.

One ladder, same shape as the TTS ladder (Kokoro → Piper → silent): prefer
Moonshine (beats Whisper-large-v3 at 250M params, ~5x faster on short windows —
the wearable-latency class) when its ONNX export is present, else faster-whisper,
else None. Every engine exposes the same `transcribe(audio) -> str` contract the
CapturePipeline calls, so the pipeline is engine-agnostic. Absent every wheel it
returns None and the pipeline simply produces no transcript — unchanged.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("dreamlayer.asr_select")


def make_asr(moonshine_dir: Optional[str] = None,
             whisper_model: Optional[str] = None):
    """The first ready ASR engine (Moonshine → faster-whisper), or None.

    Both engines coerce arbitrary audio to mono-16k internally and never raise
    into the capture loop. `moonshine_dir` overrides $DL_MOONSHINE_DIR; a whisper
    model size overrides the profile default."""
    try:
        from .asr_moonshine import default_moonshine
        m = default_moonshine(moonshine_dir)
        if m is not None:
            log.info("[asr] using Moonshine (%s)", getattr(m, "model_dir", "?"))
            return m
    except Exception as exc:                       # noqa: BLE001 — never fail wiring
        log.debug("[asr] moonshine unavailable: %s", exc)
    try:
        from .asr_faster_whisper import FasterWhisperASR
        if FasterWhisperASR.available:
            fw = FasterWhisperASR(whisper_model) if whisper_model \
                else FasterWhisperASR()
            if getattr(fw, "_model", None) is not None:
                log.info("[asr] using faster-whisper")
                return fw
    except Exception as exc:                       # noqa: BLE001
        log.debug("[asr] faster-whisper unavailable: %s", exc)
    return None


def asr_engine_name(asr) -> str:
    """A short honest label of which engine is live (for status surfaces)."""
    if asr is None:
        return "none"
    cls = type(asr).__name__
    return {"MoonshineASR": "moonshine",
            "FasterWhisperASR": "faster-whisper"}.get(cls, cls.lower())
