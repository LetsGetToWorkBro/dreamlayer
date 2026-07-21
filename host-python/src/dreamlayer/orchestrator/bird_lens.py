"""orchestrator/bird_lens.py — the world narrates itself: a Birdsong lens.

BirdNET (Cornell Lab / Chemnitz) recognizes 6,000+ species from sound with a
model tiny enough for a Pi Zero. You're on a walk; the glasses whisper "that's a
Song Sparrow." It rides the SAME ambient-audio rung as sound_events — and the
same posture: it classifies bird song, a sound with no human identity, and
nothing leaves the Brain.

Split like sound_events: `BirdSongLens.identify()` is the lazy model (extras
group `birds`, birdnetlib); `bird_alert()` is the PURE policy that turns
detections into one gentle "listen" Alert for the attention engine — testable
with no model. Location/date, when known, narrow the species list exactly as
BirdNET intends; both are optional.
"""
from __future__ import annotations

import logging
import tempfile
import wave
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .attention import Alert

log = logging.getLogger("dreamlayer.bird_lens")

_SR = 48000                      # BirdNET's native rate
_MIN_CONF = 0.5                  # whisper only when fairly sure — a wrong bird is worse than none


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def bird_alert(detections, min_conf: float = _MIN_CONF) -> Optional[Alert]:
    """PURE: the single best bird detection → one gentle Alert, or None. NaN /
    malformed confidences are rejected (same lesson as sound_events)."""
    best: Optional[Tuple[float, str]] = None
    for item in (detections or []):
        try:
            name, conf = str(item[0]).strip(), float(item[1])
        except (TypeError, ValueError, LookupError):
            continue
        if not name or not (conf >= min_conf):     # NaN fails this too
            continue
        if best is None or conf > best[0]:
            best = (conf, name)
    if best is None:
        return None
    name = best[1]
    return Alert("listen", f"That's a {name}", "singing nearby",
                 f"bird:{name.lower()}")


class BirdSongLens:
    """Wrap the BirdNET analyzer (birdnetlib). `available` is the wheel; `ready`
    once the analyzer (and its bundled model) actually loaded."""

    dep = "birdnetlib"
    available = _has("birdnetlib")

    def __init__(self, lat: Optional[float] = None, lon: Optional[float] = None):
        self._analyzer: Any = None
        self._loaded = False
        self.lat, self.lon = lat, lon

    def _load(self) -> bool:
        if self._loaded:
            return self._analyzer is not None
        self._loaded = True
        if not self.available:
            return False
        try:
            from birdnetlib.analyzer import Analyzer  # type: ignore
            self._analyzer = Analyzer()
        except Exception as exc:                   # noqa: BLE001
            log.info("[birds] analyzer load failed: %s", exc)
            self._analyzer = None
        return self._analyzer is not None

    @property
    def ready(self) -> bool:
        return self._load()

    def identify(self, audio, sample_rate: int = _SR,
                 when=None) -> List[Tuple[str, float]]:
        """[(common name, confidence), …] for bird song in an audio window, or []
        when unavailable / nothing sings / anything fails. birdnetlib's stable
        API is file-based, so the window goes through a temp WAV (deleted after)."""
        if not self._load():
            return []
        from .sound_events import _to_mono
        mono = _to_mono(audio, sample_rate, _SR)
        if mono is None:
            return []
        try:
            import numpy as np
            from birdnetlib import Recording  # type: ignore
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "window.wav"
                pcm = (np.clip(mono, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
                with wave.open(str(p), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(_SR)
                    wf.writeframes(pcm)
                kw: dict = {}
                if self.lat is not None and self.lon is not None:
                    kw.update(lat=self.lat, lon=self.lon)
                if when is not None:
                    kw.update(date=when)
                rec = Recording(self._analyzer, str(p), min_conf=0.25, **kw)
                rec.analyze()
                out = [(str(d.get("common_name", "")).strip(),
                        float(d.get("confidence", 0.0)))
                       for d in (rec.detections or [])]
                return [(n, c) for n, c in out if n]
        except Exception as exc:                   # noqa: BLE001
            log.error("[birds] identify failed: %s", exc)
            return []

    def listen(self, audio, sample_rate: int = _SR, when=None) -> Optional[Alert]:
        """Identify + policy in one call — the Alert to hand to the same hark
        path sound_events feeds (which carries Veil/Focus gating + cooldown)."""
        return bird_alert(self.identify(audio, sample_rate, when))


def default_bird_lens(lat=None, lon=None) -> Optional[BirdSongLens]:
    b = BirdSongLens(lat, lon)
    return b if b.available else None
