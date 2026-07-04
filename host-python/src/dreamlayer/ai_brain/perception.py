"""ai_brain/perception.py — Tier 0: the on-glass perception seam.

The cheapest tier. Not rich explanation (that is `VisionBrain.explain`, which
returns an `Answer`); fast, structured *perception*:

    Perceptor.perceive(frame) -> PerceptSignals   # face?, text density, form grid, object?, lang
    Perceptor.listen(audio)   -> AudioPercept      # wake-word confidence, VAD, keyword id

Today this ships as a **heuristic with no model**, so the whole pipeline — the
Glance Arbiter's coarse read, wake-word — runs offline with nothing installed.

On Halo, the Alif Balletto B1's **Ethos-U55 NPU** runs a Vela-compiled int8
model behind the *same* protocol: `NpuPerceptor` wraps an `infer_fn` and maps
its output to the same `PerceptSignals`. Nothing upstream changes — the Glance
Arbiter and wake-word draw from `PerceptionRouter`, which prefers the NPU when
present and falls back to the heuristic when it isn't. A dead tier is skipped,
never fatal — the same discipline as `BrainRouter`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, runtime_checkable

import numpy as np


# --- what a perception pass yields ------------------------------------------

@dataclass
class PerceptSignals:
    """Coarse cues from one frame. Mirrors the keys the Glance Arbiter's
    `classify_coarse` consumes, so `as_signals()` drops straight in as the
    `_glance_signals_fn` seam. Fields left None are 'the tier couldn't tell'
    (a heuristic can't see a face; a model can) and are simply omitted."""
    has_face: Optional[bool] = None
    text_density: Optional[float] = None
    form_fields: Optional[int] = None
    question: Optional[bool] = None
    has_object: Optional[bool] = None
    language: Optional[str] = None
    tier: str = ""

    def as_signals(self) -> dict:
        """The dict shape the coarse classifier reads. Only known cues are
        included, so an absent field never masquerades as a negative."""
        out: dict = {}
        if self.has_face is not None:
            out["has_face"] = self.has_face
        if self.text_density is not None:
            out["text_density"] = round(float(self.text_density), 3)
        if self.form_fields is not None:
            out["form_fields"] = int(self.form_fields)
        if self.question is not None:
            out["question"] = bool(self.question)
        if self.has_object is not None:
            out["has_object"] = bool(self.has_object)
        if self.language:
            out["language"] = self.language
        return out


@dataclass
class AudioPercept:
    """Coarse cues from an audio window: is a wake-word present, is anyone
    speaking (VAD), and an optional keyword id for a small command set."""
    wake: float = 0.0                # wake-word confidence 0..1
    speaking: bool = False           # voice activity
    keyword: str = ""                # a spotted command ("", "save", "veil"…)
    tier: str = ""

    def woke(self, threshold: float = 0.5) -> bool:
        return self.wake >= threshold


# --- the protocol any tier implements ---------------------------------------

@runtime_checkable
class Perceptor(Protocol):
    tier: str
    is_npu: bool

    def perceive(self, frame) -> Optional[PerceptSignals]: ...
    def listen(self, audio) -> Optional[AudioPercept]: ...


# --- cheap image stats (no model) -------------------------------------------

def _as_gray(frame) -> np.ndarray:
    a = np.asarray(frame, dtype=np.float32)
    if a.ndim == 3:
        a = a.mean(axis=2)
    return a


def text_density(frame) -> float:
    """A model-free density estimate: mean gradient magnitude normalised by the
    frame's dynamic range. Text and dense edges score high; a flat wall scores
    ~0. Cheap, deterministic, and honest about what a heuristic can know."""
    a = _as_gray(frame)
    if a.size == 0 or a.shape[0] < 2 or a.shape[1] < 2:
        return 0.0
    gx = float(np.abs(np.diff(a, axis=1)).mean())
    gy = float(np.abs(np.diff(a, axis=0)).mean())
    rng = float(a.max() - a.min()) or 1.0
    return max(0.0, min(1.0, 1.5 * (gx + gy) / rng))


# --- Tier 0 today: a heuristic, no model ------------------------------------

class HeuristicPerceptor:
    """The zero-model Tier 0. Produces only what image stats can honestly give
    — a text-density estimate and a coarse object-present flag — and merges any
    externally supplied cues (`hint_fn`, the old device seam). It never claims a
    face, a form grid, or a language: those need a model, so it leaves them
    unset and the NPU tier fills them in."""
    tier = "heuristic"
    is_npu = False

    def __init__(self, hint_fn: Optional[Callable[[object], dict]] = None,
                 object_density: float = 0.06, object_cap: float = 0.5):
        self._hint = hint_fn
        self._obj_lo = object_density        # some structure, not a blank wall
        self._obj_hi = object_cap            # but not a dense wall of text

    def perceive(self, frame) -> PerceptSignals:
        d = text_density(frame)
        sig = PerceptSignals(text_density=d, tier=self.tier)
        # a mid-contrast, not-text-dense scene reads as "an object is here"
        if self._obj_lo <= d < self._obj_hi:
            sig.has_object = True
        if self._hint is not None:
            try:
                self._merge(sig, self._hint(frame) or {})
            except Exception:
                pass
        return sig

    @staticmethod
    def _merge(sig: PerceptSignals, hints: dict) -> None:
        if "has_face" in hints:
            sig.has_face = bool(hints["has_face"])
        if "form_fields" in hints:
            sig.form_fields = int(hints["form_fields"])
        if "question" in hints:
            sig.question = bool(hints["question"])
        if "language" in hints and hints["language"]:
            sig.language = str(hints["language"])
        if "text_density" in hints:          # a device estimate overrides ours
            sig.text_density = float(hints["text_density"])
        if hints.get("has_object") or hints.get("object"):
            sig.has_object = True

    def listen(self, audio) -> AudioPercept:
        return AudioPercept(tier=self.tier)   # no model: never wakes on its own


# --- Tier 0 on Halo: a quantized model on the Ethos-U55 NPU -----------------

class NpuPerceptor:
    """The real Tier 0. `vision_fn(frame) -> dict` and `audio_fn(audio) -> dict`
    are the seams a Vela-compiled Ethos-U55 model plugs into (off-glass, an
    ONNX/Ollama model on the Mac fits the same hole). This class owns the
    boundary — it maps raw model output to the typed percepts — so the model
    can be swapped without touching a caller.

    Output contract (all keys optional): vision → {has_face, text_density,
    form_fields, question, has_object, language}; audio → {wake, speaking,
    keyword}.
    """
    is_npu = True

    def __init__(self, vision_fn: Optional[Callable[[object], dict]] = None,
                 audio_fn: Optional[Callable[[object], dict]] = None,
                 tier: str = "npu"):
        self.tier = tier
        self._vision = vision_fn
        self._audio = audio_fn

    def perceive(self, frame) -> Optional[PerceptSignals]:
        if self._vision is None:
            return None                       # no model wired — router falls back
        out = self._vision(frame)
        if not out:
            return None                       # model declined — defer to fallback
        return PerceptSignals(
            has_face=_opt_bool(out.get("has_face")),
            text_density=_opt_float(out.get("text_density")),
            form_fields=_opt_int(out.get("form_fields")),
            question=_opt_bool(out.get("question")),
            has_object=_opt_bool(out.get("has_object")),
            language=(str(out["language"]) if out.get("language") else None),
            tier=self.tier)

    def listen(self, audio) -> Optional[AudioPercept]:
        if self._audio is None:
            return None
        out = self._audio(audio)
        if not out:
            return None
        return AudioPercept(wake=float(out.get("wake", 0.0) or 0.0),
                            speaking=bool(out.get("speaking", False)),
                            keyword=str(out.get("keyword", "") or ""),
                            tier=self.tier)


def _opt_bool(v): return None if v is None else bool(v)
def _opt_int(v): return None if v is None else int(v)
def _opt_float(v): return None if v is None else float(v)


# --- the router: prefer the NPU, fall back to the heuristic -----------------

class PerceptionRouter:
    """Holds perceptors in preference order and answers from the best one that
    can. Same shape as `BrainRouter`: a dead or model-less tier returns None
    and is skipped; the heuristic tier always answers, so perception never
    fails. Seeded with the heuristic so it works the moment it's constructed."""

    def __init__(self, perceptors: Optional[list] = None):
        self._perceptors: list = (list(perceptors) if perceptors is not None
                                  else [HeuristicPerceptor()])

    def add_perceptor(self, p, prefer: bool = True) -> None:
        """Register a tier. prefer=True puts it ahead of the rest (the NPU wants
        first crack); prefer=False appends it as a lower fallback."""
        if prefer:
            self._perceptors.insert(0, p)
        else:
            self._perceptors.append(p)

    def has_npu(self) -> bool:
        return any(getattr(p, "is_npu", False) for p in self._perceptors)

    def perceive(self, frame) -> PerceptSignals:
        for p in self._perceptors:
            try:
                r = p.perceive(frame)
            except Exception:
                continue
            if r is not None:
                return r
        return PerceptSignals()

    def listen(self, audio) -> AudioPercept:
        for p in self._perceptors:
            try:
                r = p.listen(audio)
            except Exception:
                continue
            if r is not None:
                return r
        return AudioPercept()
