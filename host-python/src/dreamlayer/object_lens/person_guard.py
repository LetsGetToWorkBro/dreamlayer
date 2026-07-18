"""object_lens/person_guard.py — layered "never identify a stranger" defence.

Refusing to identify a stranger is the product's hardest privacy rule. The
recognizer already refuses generic person-words and proper-name shapes
(recognizer._names_a_person). This module adds two OPTIONAL, fail-safe layers
that harden the places a VLM can still slip an identity through:

  * TEXT  — Presidio NER on the label catches a personal NAME the shape rule
            can't (a lone given name like "Maya", an odd capitalisation). Uses
            the presidio-analyzer already shipped in the `privacy` extra.
  * VISUAL— a person DETECTOR on the frame (detection, NEVER recognition — we
            only learn THAT a human is the subject, never WHO) defers a frame the
            VLM mislabelled as an object. Uses the `vision` extra's detector.

Both layers are lazy, cached, and wrapped so a missing dependency or ANY error
degrades to a no-op: a layer can only ADD a deferral, never remove one. With
neither dep installed the deterministic recognizer defence stands alone,
unchanged. Detectors are injectable (module-level overrides) so the layering is
unit-tested without the heavy optional deps present.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger("dreamlayer.person_guard")

# Minimum Presidio confidence for a PERSON entity to count. Presidio's spaCy NER
# scores a clear name ~0.85; keep the floor high so a common noun mis-tagged as a
# name doesn't defer a legitimate object.
_PERSON_SCORE_MIN = 0.6
# A detected person must cover at least this fraction of the frame to be the
# SUBJECT of the look (a bystander in the corner is not what the wearer aimed at).
_PERSON_AREA_MIN = 0.18

# Injectable hooks (tests set these; production leaves them None → lazy default).
# _analyzer(text) -> list of (entity_type, score); _detector(frame) -> list of
# (label, confidence, area_fraction). Set to the sentinel _NONE to mean "tried and
# unavailable" so we don't re-attempt a failed import every call.
_analyzer_override: Optional[Callable] = None
_detector_override: Optional[Callable] = None
_NONE = object()
_analyzer_cache: object = None
_detector_cache: object = None


def reset_caches() -> None:
    """Drop the lazy-loaded analyzer/detector (tests use this between cases)."""
    global _analyzer_cache, _detector_cache
    _analyzer_cache = None
    _detector_cache = None


def _get_analyzer():
    """The Presidio analyzer, lazily built once. Returns None when presidio isn't
    installed or fails to initialise — the caller then simply skips the text
    layer."""
    global _analyzer_cache
    if _analyzer_override is not None:
        return _analyzer_override
    if _analyzer_cache is _NONE:
        return None
    if _analyzer_cache is not None:
        return _analyzer_cache
    try:
        from presidio_analyzer import AnalyzerEngine
        engine = AnalyzerEngine()

        def _analyze(text: str):
            res = engine.analyze(text=text, language="en", entities=["PERSON"])
            return [(r.entity_type, float(r.score)) for r in res]

        _analyzer_cache = _analyze
        return _analyze
    except Exception as exc:                       # presidio/spaCy absent or model missing
        log.debug("[person_guard] presidio unavailable: %s", exc)
        _analyzer_cache = _NONE
        return None


def label_is_a_person(label: str) -> bool:
    """True when Presidio recognises a PERSON name in the label. Fail-safe: any
    error or a missing dep returns False (the deterministic defence still ran)."""
    if not label or not label.strip():
        return False
    analyzer = _get_analyzer()
    if analyzer is None:
        return False
    try:
        for entity, score in analyzer(label):
            if entity == "PERSON" and score >= _PERSON_SCORE_MIN:
                return True
    except Exception as exc:                       # noqa: BLE001 — never break a look
        log.debug("[person_guard] label analysis failed: %s", exc)
    return False


def _get_detector():
    """The person detector, lazily built once. Returns None when the vision extra
    (ultralytics) isn't installed — the caller then skips the visual layer."""
    global _detector_cache
    if _detector_override is not None:
        return _detector_override
    if _detector_cache is _NONE:
        return None
    if _detector_cache is not None:
        return _detector_cache
    try:
        from ultralytics import YOLO
        model = YOLO("yolo11n.pt")                 # nano detector — person is class 0

        def _detect(frame):
            out = model.predict(frame, verbose=False, classes=[0])  # persons only
            hits = []
            for r in out:
                h, w = (r.orig_shape or (1, 1))[:2]
                area = float(w * h) or 1.0
                for b in r.boxes:
                    x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
                    frac = ((x2 - x1) * (y2 - y1)) / area
                    hits.append(("person", float(b.conf[0]), frac))
            return hits

        _detector_cache = _detect
        return _detect
    except Exception as exc:                       # ultralytics absent / model download blocked
        log.debug("[person_guard] person detector unavailable: %s", exc)
        _detector_cache = _NONE
        return None


def frame_is_dominated_by_a_person(frame) -> bool:
    """True when a person is the dominant subject of the frame — a visual ground
    truth that defers even when the VLM mislabelled the human as an object.
    Detection only (never identity). Fail-safe: no detector / any error → False."""
    if frame is None:
        return False
    detector = _get_detector()
    if detector is None:
        return False
    try:
        for label, conf, area in detector(frame):
            if label == "person" and conf >= 0.5 and area >= _PERSON_AREA_MIN:
                return True
    except Exception as exc:                       # noqa: BLE001 — never break a look
        log.debug("[person_guard] frame detection failed: %s", exc)
    return False
