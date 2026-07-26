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

from dataclasses import dataclass
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
    # Tier-1 scene cues (2026-07-23): the arbiter always consumed items/shelf/menu
    # but nothing produced them, so a shelf could never be recognised. `sky` and
    # `moving` are new scene inputs the arbiter learned to read alongside them.
    items: Optional[int] = None
    shelf: Optional[bool] = None
    menu: Optional[bool] = None
    sky: Optional[bool] = None
    moving: Optional[bool] = None
    bands: Optional[int] = None      # horizontal text/table bands
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
        if self.items is not None:
            out["items"] = int(self.items)
        if self.shelf is not None:
            out["shelf"] = bool(self.shelf)
        if self.menu is not None:
            out["menu"] = bool(self.menu)
        if self.sky is not None:
            out["sky"] = bool(self.sky)
        if self.moving is not None:
            out["moving"] = bool(self.moving)
        if self.bands is not None:
            out["bands"] = int(self.bands)
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
    frame's FULL intensity scale. Text and dense edges score high; a flat wall
    scores ~0. Cheap, deterministic, and honest about what a heuristic can know.

    Normalising by the per-frame dynamic range (max-min) was the bug: a flat
    wall with a single LSB of sensor noise has range 1 and gradient ~1, so the
    ratio SATURATED to 1.0 — noise read as maximal text. Dividing by the fixed
    full scale (255 for int frames, 1.0 for float) makes absolute contrast the
    signal, so a near-flat frame scores near 0 as the docstring promises."""
    a = _as_gray(frame)
    if a.size == 0 or a.shape[0] < 2 or a.shape[1] < 2:
        return 0.0
    gx = float(np.abs(np.diff(a, axis=1)).mean())
    gy = float(np.abs(np.diff(a, axis=0)).mean())
    full = 255.0 if float(a.max()) > 1.0 else 1.0
    return max(0.0, min(1.0, 1.5 * (gx + gy) / full))


def _downs(a: np.ndarray, target: int = 128) -> np.ndarray:
    """Cheap nearest-neighbour downsample so every cue below is O(128²)."""
    h, w = a.shape[:2]
    if max(h, w) <= target:
        return a
    step = max(1, int(max(h, w) / target))
    return a[::step, ::step]


def _boxds(a: np.ndarray, target: int = 512) -> np.ndarray:
    """Box-AVERAGE downsample — used where striding would lie.

    `_downs` strides, which is fine for structural cues but catastrophic for a
    sharpness measure: any detail commensurate with the stride aliases straight
    through, so a crisp fine grating reads as flat (= "blurred = the wearer is
    walking") while genuine motion blur, whose energy is spread, reads however the
    stride happens to land. Averaging into blocks cannot alias — a blurred frame
    stays blurred and a sharp one stays sharp at any input size. Frames already
    at or below `target` are returned untouched, so the common 512-px look path
    measures the real pixels."""
    h, w = a.shape[:2]
    k = max(1, int(max(h, w) // target))
    if k <= 1:
        return a.astype(np.float64, copy=False)
    hh, ww = (h // k) * k, (w // k) * k
    if hh < k or ww < k:
        return a.astype(np.float64, copy=False)
    b = a[:hh, :ww].astype(np.float64)
    return b.reshape(hh // k, k, ww // k, k).mean(axis=(1, 3))


def _peaks(prof: np.ndarray, min_prom: float = 0.18, min_gap: int = 3,
           min_range: float = 0.02) -> int:
    """Count prominent, well-separated peaks in a 1-D profile. The repetition
    detector: a shelf of bottles or a menu's rows put regular spikes in the
    gradient profile, a single mug does not.

    `min_range` is what makes it a structure detector rather than a noise meter.
    Prominence is measured RELATIVE to the profile's own range, so on a flat frame
    — a blank wall with a little sensor noise — the noise IS the range and roughly
    every other sample cleared the bar: a painted wall reported ~25 repetitions
    out of nothing. Measured, in profile units of full-scale gradient: a blank
    wall's range is ~0.002, a wall with a lighting gradient ~0.003, while real
    structure is an order of magnitude up (a radiator 0.14, a shelf 0.31, a
    printed page 0.51). Below `min_range` there is no structure to count."""
    if prof.size < 8:
        return 0
    p = prof - prof.min()
    rng = float(p.max())
    if rng < min_range:
        return 0
    p = p / rng
    n, last = 0, -min_gap - 1
    for i in range(1, len(p) - 1):
        if p[i] >= min_prom and p[i] >= p[i - 1] and p[i] >= p[i + 1] and (i - last) > min_gap:
            n += 1
            last = i
    return n


def frame_cues(frame) -> dict:
    """Model-free scene cues the Glance Arbiter can act on, from one frame.

    The arbiter was built to read ten signals but the live path only ever fed it
    two (text_density, has_object), so every scene in the world collapsed to
    "text" or "object" and shelf/menu/sky could never be resolved — the arbiter
    was blind, not indecisive (audit 2026-07-23). These are deliberately cheap,
    deterministic, numpy-only cues with honest names:

      col_reps    repetition along COLUMNS — things side by side, e.g. a shelf
      row_reps    repetition along ROWS — text lines
      rows        strong horizontal bands, the signature of a form/table
      contrast    spread of luminance; distinguishes a blurred SCENE from a
                  featureless wall, which no sharpness measure can
      dark        overall luminance is low (dusk, indoors-dim, night sky)
      light_frac  bright pixels as a fraction of the frame
      lights      how many separate bright runs there are
      light_len   their mean length — stars are tiny, a lamp or a screen is not
      light_up    the fraction of rows containing a bright pixel; stars are spread
                  across the frame, an LED cluster is not
      sharp       high-frequency energy; LOW means the frame is blurred, which on
                  a phone means the wearer is MOVING (walking)

    Everything here is a heuristic and is reported as such: absent/uncertain cues
    are simply omitted so they never masquerade as a negative."""
    out: dict = {}
    a0 = _as_gray(frame)
    if a0.size == 0 or a0.shape[0] < 8 or a0.shape[1] < 8:
        return out
    a = _downs(a0)
    full = 255.0 if float(a.max()) > 1.0 else 1.0
    g = a / full
    gx = np.abs(np.diff(g, axis=1))
    gy = np.abs(np.diff(g, axis=0))
    # Repetition, PER AXIS — this separation is the whole trick. A printed page
    # repeats along ROWS (text lines); a shelf of items repeats along COLUMNS
    # (things side by side). Taking max() of the two made every page a shelf.
    out["col_reps"] = int(_peaks(gx.mean(axis=0)))
    out["row_reps"] = int(_peaks(gy.mean(axis=1)))
    rowe = gy.mean(axis=1)
    med = float(np.median(rowe))
    out["rows"] = int(np.count_nonzero(rowe > (med * 2.5 + 1e-6)))
    # How much luminance VARIES. A blurred street and a blank wall both have
    # almost no high-frequency energy and almost no gradient, so neither sharpness
    # nor text-density can tell them apart — but the street still has large shapes
    # in it and the wall does not. Measured: a wall 0.003 (0.027 with a lighting
    # gradient), motion-blurred scenes 0.11-0.14.
    out["contrast"] = round(float(g.std()), 5)
    # The light cues need REAL pixels. A star is 1-2 px wide, so the strided
    # downsample above deletes most of a starfield and keeps whatever happens to
    # land on the stride — which is why a single LED in a dark room used to look
    # exactly like the Milky Way. Box-average instead, and only below 512 px is
    # that a no-op, so the common look path measures the frame as decoded.
    gf = _boxds(a0)
    gf = gf / (255.0 if float(gf.max()) > 1.0 else 1.0)
    mean_l = float(gf.mean())
    out["dark"] = bool(mean_l < 0.28)
    if out["dark"]:
        mask = gf > max(0.55, mean_l + 0.35)
        nbright = int(np.count_nonzero(mask))
        out["light_frac"] = round(nbright / float(mask.size), 5)
        if nbright:
            # count separate bright RUNS and their mean length: a sky is many tiny
            # ones spread over the frame, a lamp or a phone screen is a few long
            # ones in one place. This is what separates the two, not the total.
            p = np.zeros((mask.shape[0], mask.shape[1] + 2), dtype=np.int8)
            p[:, 1:-1] = mask
            runs = int(np.count_nonzero(np.diff(p, axis=1) == 1))
            out["lights"] = runs
            out["light_len"] = round(nbright / float(runs), 3) if runs else 0.0
            # How far across the frame they are SCATTERED, as the bright pixels'
            # bounding box on each axis. Stars are spread over the whole view; an
            # LED, a phone screen or a row of streetlamps occupies one patch. The
            # fraction of ROWS containing a light looked like the same measure but
            # is not — a real, sparse starfield of a dozen points touches only 5%
            # of the rows while still covering the entire frame.
            rows_hit = np.flatnonzero(mask.any(axis=1))
            cols_hit = np.flatnonzero(mask.any(axis=0))
            out["light_spany"] = round(
                float(rows_hit[-1] - rows_hit[0] + 1) / float(mask.shape[0]), 4)
            out["light_spanx"] = round(
                float(cols_hit[-1] - cols_hit[0] + 1) / float(mask.shape[1]), 4)
    if gf.shape[0] > 4 and gf.shape[1] > 4:
        lap = np.abs(np.diff(gf, n=2, axis=0)).mean() + np.abs(np.diff(gf, n=2, axis=1)).mean()
        out["sharp"] = round(float(lap), 5)
    return out


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
        # Tier-1 cues: turn the cheap frame statistics into the scene inputs the
        # arbiter has always been able to read (audit 2026-07-23). Deliberately
        # conservative — a cue we can't justify is left unset, never guessed.
        try:
            c = frame_cues(frame)
        except Exception:                    # noqa: BLE001 — a cue never breaks a look
            c = {}
        if c:
            # A SHELF is deliberately NOT claimed from image statistics, for the
            # same reason `menu` never was: to a gradient profile a bookshelf, a
            # radiator, a picket fence and a venetian blind are one picture. The
            # earlier version claimed "12 items to compare" on a radiator and on a
            # motion-blurred street, and still missed a real 4-bottle shelf — a
            # detector that is wrong in both directions is worse than no detector.
            # `shelf`/`items` come from the phone's own object detector instead
            # (several detections, and several of the SAME label), which is a real
            # witness to "comparable things side by side" rather than an inference
            # from periodicity. Repetition is still reported raw, as col_reps /
            # row_reps, for cues where periodicity alone is the honest signal.
            # Horizontal banding is the signature of PRINT. Exposed on its own so
            # a lens can recognise a page even when the single-number density
            # metric under-reads thin type (it measures mean gradient, so fine
            # print on white scores lower than its legibility suggests).
            bands = int(c.get("rows", 0) or 0)
            if bands:
                sig.bands = min(99, bands)
            # A FORM/table: a FEW strong horizontal bands over text, with vertical
            # rules crossing them. Both extra clauses are corrections: `bands >= 6
            # and d >= 0.20` alone is satisfied by any densely-set page, because
            # text lines ARE horizontal bands — the same cue Read depends on — so a
            # photographed page of prose claimed 12 form fields and the glasses
            # offered to fill it in. A form has on the order of six to twenty rows;
            # a page of prose has forty to seventy, and no column rules.
            if 6 <= bands <= 24 and d >= 0.20 and int(c.get("col_reps", 0) or 0) >= 2:
                sig.form_fields = min(12, bands // 2)
            # THE SKY: a dark field, almost no text, and MANY tiny bright points
            # spread across the frame. All three clauses are load-bearing, and the
            # earlier "small bright fraction" test was none of them: a dark room
            # with one LED, a night street under lamps, and a dim room lit by a
            # phone screen all claimed the night sky and fired an astronomy lens.
            # Measured on JPEG round-tripped frames: a starfield gives many runs of
            # mean length 1-2 scattered over ~99% of both axes; one LED 6 runs of
            # length 6 inside 1% of the frame; three streetlamps 54 runs of length
            # 16 across 4% of the rows; a lit wall one run per row of length 120.
            if (c.get("dark") and d < 0.12
                    and int(c.get("lights", 0) or 0) >= 8
                    and 0.0 < float(c.get("light_len", 0.0) or 0.0) <= 4.0
                    and float(c.get("light_spany", 0.0) or 0.0) >= 0.4
                    and float(c.get("light_spanx", 0.0) or 0.0) >= 0.4):
                sig.sky = True
            # MOVING: the frame is smeared but there IS a scene in it. `contrast`
            # is what makes that second half real — a blank wall is not "walking",
            # it is just blank, and text_density cannot tell the two apart because
            # blur destroys density too (a blurred street measures 0.005, the same
            # as a painted wall). Set only when true, never as a claimed negative.
            sharp, con = c.get("sharp"), float(c.get("contrast", 0.0) or 0.0)
            if sharp is not None and con >= 0.08 and float(sharp) < 0.003:
                sig.moving = True
        # NOTE: `menu` is deliberately never claimed from image statistics — a menu
        # and a page of prose are not separable this way. It stays available for the
        # phone's detector / a VLM tier to supply.
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
        # the phone's own on-device detector is a far better witness than image
        # statistics — let its cues override ours when it supplies them
        if "items" in hints:
            try:
                sig.items = max(int(sig.items or 0), int(hints["items"]))
            except (TypeError, ValueError):
                pass
        for k in ("shelf", "menu", "sky", "moving"):
            if hints.get(k):
                setattr(sig, k, True)

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
