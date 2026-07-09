"""Facial Action Unit backends — LibreFace / py-feat / facetorch / OpenFace-3.0.

ADD-alongside: new siblings to au_detector.py (untouched). Each class matches
the `AUDetector.process(au_frame) -> AUFrame` seam so it can be injected where
the host wants a stronger AU extractor. All lazy-import their dep (extras group
`intelligence` / `vision`); when absent, `process()` returns the input frame
unchanged (passthrough) so the 9-stage pipeline behaves exactly as today.

Wire (no host edit needed elsewhere): pass an instance anywhere an object with
`.process(au_frame)` is accepted, or call `.process()` directly.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.au_backends")


def _try(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


class _AUBackend:
    """Common shape: passthrough fallback, real path overridden by subclasses."""
    dep = ""
    available = False

    def process(self, au_frame):
        if not self.available or au_frame is None:
            return au_frame
        try:
            return self._extract(au_frame)
        except Exception as exc:  # any inference failure → safe passthrough
            log.warning("[au:%s] extract failed: %s; passthrough", self.dep, exc)
            return au_frame

    def _extract(self, au_frame):  # pragma: no cover - overridden
        return au_frame


class LibreFaceAU(_AUBackend):
    """WACV-2024 LibreFace — 41 AUs, CPU/GPU, TorchScript-exportable."""
    dep = "libreface"
    available = _try("libreface")


class PyFeatAU(_AUBackend):
    """py-feat — AUs + emotion + valence/arousal + gaze + head-pose in one pass."""
    dep = "feat"
    available = _try("feat")


class FaceTorchAU(_AUBackend):
    """facetorch — single TorchScript backbone (detect + AU + verify)."""
    dep = "facetorch"
    available = _try("facetorch")


class OpenFace3AU(_AUBackend):
    """CMU OpenFace 3.0 — AUs + gaze; gaze can feed a Presence signal."""
    dep = "openface"
    available = _try("openface")
