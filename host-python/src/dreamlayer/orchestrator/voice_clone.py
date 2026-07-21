"""Zero-shot voice cloning — speak arbitrary text in Juno's OWN voice, offline.

`_juno_say` and the Brain's /tts endpoint want *her* voice, not a stock one.
XTTS-v2 (the `coqui-tts` package) clones a timbre at INFERENCE from a handful of
reference clips — no training, no cloud, no API credits. We point it straight at
Juno's already-baked voice takes (`assets/juno_*.mp3`), so her cloned voice is
built from the voice she already has. OpenVoice slots into the same seam if
preferred; XTTS is the one-call path.

Same interface as PiperTTS (`available` / `ready` / `voice_name` / `synthesize`
→ WAV bytes | None), so the caller picks whichever engine is ready and this stays
a silent no-op when the wheel or the reference clips are absent.
"""
from __future__ import annotations

import io
import logging
import wave
from pathlib import Path
from typing import Optional, Sequence

log = logging.getLogger("dreamlayer.voice_clone")

try:  # optional dep — extras group `voice-clone`
    import TTS  # type: ignore  # noqa: F401
    _HAS_XTTS = True
except Exception:  # ImportError, or a half-built native wheel
    _HAS_XTTS = False

_XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"


class CloneTTS:
    """Clone Juno's voice from her reference clips. `ready` is True only when the
    engine imported AND at least one reference clip exists AND the model loaded."""

    available = _HAS_XTTS

    def __init__(self, reference: Sequence[object] = (),
                 model: str = _XTTS_MODEL, rate: int = 24000):
        self._tts = None
        self.voice_name = "juno"
        self._rate = rate
        self._ref = [str(p) for p in (reference or [])
                     if _exists(p)]
        if not _HAS_XTTS or not self._ref:
            return
        try:
            from TTS.api import TTS  # type: ignore
            # progress_bar off so it never scribbles on a headless log; the model
            # loads once (the caller caches the instance).
            self._tts = TTS(model_name=model, progress_bar=False)
        except Exception as exc:                       # noqa: BLE001
            log.info("[clone] XTTS load failed (%s); falling back", exc)
            self._tts = None

    @property
    def ready(self) -> bool:
        return self._tts is not None

    def synthesize(self, text: str) -> Optional[bytes]:
        """WAV bytes for `text` in Juno's cloned voice, or None on any failure."""
        text = (text or "").strip()
        if not text or self._tts is None:
            return None
        try:
            import numpy as np
            wav = self._tts.tts(text=text, speaker_wav=self._ref, language="en")
            arr = np.clip(np.asarray(wav, dtype=np.float32), -1.0, 1.0)
            pcm = (arr * 32767.0).astype("<i2").tobytes()
        except Exception as exc:                       # noqa: BLE001
            log.error("[clone] synth failed: %s", exc)
            return None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._rate)
            wf.writeframes(pcm)
        return buf.getvalue()


def _exists(p: object) -> bool:
    try:
        return Path(str(p)).is_file()
    except (OSError, TypeError, ValueError):
        return False
