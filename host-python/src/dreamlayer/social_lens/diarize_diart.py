"""Streaming diarization (diart) — "who spoke when" low-latency from a mic
stream, feeding speaker-labeled turns to identify()/meet().

ADD-alongside: new sibling (no diarization existed; timbre.py is the nearest).
Lazy-imports diart (extras group `intelligence`); when absent, `turns()` returns
a single-speaker segment so callers still get a (speaker, text) shape.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.diarize_diart")

try:
    import diart  # type: ignore  # noqa: F401
    _HAS_DIART = True
except ImportError:
    _HAS_DIART = False


class DiartDiarizer:
    available = _HAS_DIART

    def __init__(self):
        self._pipeline = None
        if _HAS_DIART:
            try:
                from diart import SpeakerDiarization  # type: ignore
                self._pipeline = SpeakerDiarization()
            except Exception as exc:
                log.warning("[diart] init failed: %s; single-speaker fallback", exc)
                self._pipeline = None

    def turns(self, audio) -> list[dict]:
        """Return [{speaker, start, end}]. Fallback = one 'spk0' turn spanning
        the whole window."""
        if self._pipeline is not None:
            try:
                ann = self._pipeline(audio)
                out = []
                for seg, _track, label in ann.itertracks(yield_label=True):
                    out.append({"speaker": str(label), "start": seg.start, "end": seg.end})
                return out or [{"speaker": "spk0", "start": 0.0, "end": None}]
            except Exception as exc:
                log.warning("[diart] run failed: %s; single-speaker", exc)
        return [{"speaker": "spk0", "start": 0.0, "end": None}]
