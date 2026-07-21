"""orchestrator/asr_moonshine.py — Moonshine: captions-class ASR, wearable-fast.

Moonshine (Moonshine AI) beats Whisper-large-v3 accuracy at 250M params and
processes short audio ~5x faster — exactly the model class the glasses' caption
and voice-ask paths want. It runs here through sherpa-onnx (already in the
`voice` extra; the same ONNX engine behind onnx_speech), so there is no new
wheel: drop the Moonshine ONNX model files in a directory and this lights up.

Model dir ($DL_MOONSHINE_DIR, or a dir you pass): preprocess.onnx, encode.onnx,
uncached_decode.onnx, cached_decode.onnx, tokens.txt — the standard sherpa
Moonshine export. Absent any of it (or sherpa-onnx), transcribe() returns ""
and callers behave exactly as today, mirroring asr_faster_whisper.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("dreamlayer.asr_moonshine")

_FILES = ("preprocess.onnx", "encode.onnx", "uncached_decode.onnx",
          "cached_decode.onnx", "tokens.txt")


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def find_moonshine_dir(explicit: Optional[str] = None) -> Optional[Path]:
    """The first directory containing a complete Moonshine export: an explicit
    path, then $DL_MOONSHINE_DIR. Incomplete dirs are skipped, not half-loaded."""
    for cand in (explicit, os.environ.get("DL_MOONSHINE_DIR")):
        if not cand:
            continue
        d = Path(cand)
        try:
            if d.is_dir() and all((d / f).is_file() for f in _FILES):
                return d
        except OSError:
            continue
    return None


class MoonshineASR:
    """Wrap a Moonshine model via sherpa-onnx. `available` is the engine wheel;
    `ready` is True only when the model files loaded."""

    dep = "sherpa_onnx"
    available = _has("sherpa_onnx")

    def __init__(self, model_dir: Optional[str] = None, num_threads: int = 1):
        self._rec: Any = None
        self.model_dir = find_moonshine_dir(model_dir)
        if not self.available or self.model_dir is None:
            return
        try:
            import sherpa_onnx  # type: ignore
            d = self.model_dir
            self._rec = sherpa_onnx.OfflineRecognizer.from_moonshine(
                preprocessor=str(d / "preprocess.onnx"),
                encoder=str(d / "encode.onnx"),
                uncached_decoder=str(d / "uncached_decode.onnx"),
                cached_decoder=str(d / "cached_decode.onnx"),
                tokens=str(d / "tokens.txt"),
                num_threads=int(num_threads))
        except Exception as exc:                       # noqa: BLE001
            log.error("[moonshine] load failed: %s; no-transcript fallback", exc)
            self._rec = None

    @property
    def ready(self) -> bool:
        return self._rec is not None

    def transcribe(self, audio, sample_rate: int = 16000) -> str:
        """Text for an audio window (any layout/rate — coerced to mono 16k), or
        "" when the engine/model is absent or anything fails. Never raises into
        the capture loop."""
        if self._rec is None:
            return ""
        from .sound_events import _to_mono
        mono = _to_mono(audio, sample_rate, 16000)
        if mono is None:
            return ""
        try:
            stream = self._rec.create_stream()
            stream.accept_waveform(16000, mono)
            self._rec.decode_stream(stream)
            return str(getattr(stream.result, "text", "") or "").strip()
        except Exception as exc:                       # noqa: BLE001
            log.error("[moonshine] transcribe failed: %s", exc)
            return ""


def default_moonshine(model_dir: Optional[str] = None) -> Optional[MoonshineASR]:
    """The recognizer when engine + model are present, else None — so a caller
    prefers Moonshine and falls back to faster-whisper exactly like the other
    engine ladders (Kokoro→Piper, panns→sherpa)."""
    m = MoonshineASR(model_dir)
    return m if m.ready else None
