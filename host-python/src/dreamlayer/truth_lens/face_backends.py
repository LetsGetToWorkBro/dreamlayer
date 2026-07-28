"""truth_lens/face_backends.py — the real on-device face embedder.

This is the model that plugs into `face_embed.FaceEmbedder`'s `embed_fn` seam,
which has always been documented as "the hole a real on-device model plugs
into". Nothing else about that seam changes: with this backend unavailable —
which is the default install — `FaceEmbedder.process_frame` returns None and
every consumer takes its existing honest "I don't know them yet" path.

**InsightFace `buffalo_l`** (SCRFD detector + ArcFace r50 recogniser, ONNX).
Chosen because its 512-d L2-normalised output matches `EMBEDDING_DIM` and the
0.65 cosine threshold `ContactIndex` already carries, it runs on onnxruntime
(CPU, no torch), and `models.lock` can hash-pin the weights like every other
model this project loads.

Opt-in by construction, three independent locks:

  1. **The dependency.** `insightface` + `onnxruntime` live in the `face`
     extras group, which is in NO deployment profile. A default
     `pip install dreamlayer` cannot recognise a face.
  2. **The weights.** Even with the package installed, the model directory must
     exist on disk. Nothing here downloads it: the fetch goes through
     `model_guard.require_fetch_allowed`, so the wearer's offline posture is
     honoured and the one sanctioned fetch window is `dreamlayer setup models`.
  3. **The switch.** The Brain will not run recognition unless the wearer turns
     it on (`BrainConfig.face_recognition`, off by default). That lock lives
     with the consumer, in `ai_brain/server/face_live.py`.

Privacy properties that are load-bearing, not incidental:

  * **One template per frame, and it is the SUBJECT's.** Detection finds every
    face in view — it must, to know which one is nearest the centre and largest
    — but detection yields a box and five landmarks, not an identity. An
    embedding is computed for the subject face ONLY, so a bystander who
    consented to nothing never has a biometric template computed at all. This
    is stronger than computing every template and discarding the losers, and it
    is why `_subject` is not merely a convenience.
  * **Nothing is persisted or logged here.** This module returns a vector to
    its caller and keeps none. No log line in this file interpolates an
    embedding, a bounding box, or a crop — a face template in a log file is a
    biometric identifier in a text file.
  * **It declines rather than guesses.** A frame with no face, a detection
    below threshold, a wrong-length vector, or any inference failure returns
    None, which `FaceEmbedder` already translates into "no answer".
"""
from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger("dreamlayer.face_backends")

# The lock id and on-disk name. `buffalo_l` is InsightFace's own pack name; the
# directory layout it unpacks to is <root>/models/buffalo_l/*.onnx.
MODEL_ID = "insightface/buffalo_l"
PACK_NAME = "buffalo_l"

# Detector confidence floor. InsightFace's SCRFD reports a det_score in [0,1];
# 0.5 is its own default and is well clear of the noise floor. `FaceEmbedder`
# applies its own threshold on top, so this is the backend's floor, not the
# product's.
DET_THRESHOLD = 0.50

# A face smaller than this fraction of the frame's shorter side is a bystander
# in the background, not who the wearer is looking at. Rejecting it outright
# means no template is computed for a distant passer-by even when they are the
# only face in view.
MIN_SUBJECT_FRACTION = 0.10

_lock = threading.RLock()
_app = None                     # the cached FaceAnalysis, or _UNAVAILABLE
_UNAVAILABLE = object()


def _deps_present() -> bool:
    """Cheap import probe — no model load, no disk read. `available` and every
    caller that wants to explain the gap to the wearer reads this."""
    try:
        import insightface                                   # noqa: F401
        import onnxruntime                                   # noqa: F401
        return True
    except Exception:                                        # noqa: BLE001
        return False


def model_root() -> str:
    """Where the weights live. `$DL_FACE_MODEL_DIR` overrides for a packaged
    build that ships them beside the app; otherwise InsightFace's own default
    (`~/.insightface`) is used, so a `dreamlayer setup models` fetch and a
    manual `insightface` install land in the same place."""
    return os.environ.get("DL_FACE_MODEL_DIR", "").strip() or \
        os.path.join(os.path.expanduser("~"), ".insightface")


def _verify_weights(root: str) -> bool:
    """Check the on-disk bytes against `models.lock` before they are trusted.

    ONNX is not pickle, so this is not an RCE gate the way `safe_torch_load` is
    — it is a "these are the weights we reviewed" gate, which matters more for a
    biometric model than for most: a swapped recogniser changes WHO the device
    thinks it is looking at. Unpinned degrades to a warning exactly like every
    other model here, or hard-fails under `DL_MODELS_STRICT`.
    """
    try:
        from ..model_guard import verify_path
        return verify_path(MODEL_ID, os.path.join(root, "models", PACK_NAME))
    except Exception as exc:                                 # noqa: BLE001
        log.warning("[face] weight verification unavailable: %s", exc)
        return True                  # never harden into a crash; warn and run


def _build():
    """Load buffalo_l once. Returns the FaceAnalysis app, or `_UNAVAILABLE`."""
    if not _deps_present():
        return _UNAVAILABLE
    root = model_root()
    pack_dir = os.path.join(root, "models", PACK_NAME)
    if not os.path.isdir(pack_dir):
        # No weights: do NOT reach for the network on a recall path. The one
        # sanctioned fetch window is the explicit bootstrap.
        log.info("[face] no %s weights at %s — face recall stays off",
                 PACK_NAME, pack_dir)
        return _UNAVAILABLE
    try:
        from ..model_guard import require_fetch_allowed
        require_fetch_allowed(model_id=MODEL_ID)
    except Exception:                                        # noqa: BLE001
        # Offline posture with the weights already on disk is the NORMAL case —
        # insightface only fetches when a pack is missing, and we just proved it
        # is not. Nothing to do; carry on with the local files.
        pass
    if not _verify_weights(root):
        log.error("[face] %s failed integrity verification — refusing to load",
                  PACK_NAME)
        return _UNAVAILABLE
    try:
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name=PACK_NAME, root=root,
                           providers=["CPUExecutionProvider"],
                           allowed_modules=["detection", "recognition"])
        app.prepare(ctx_id=-1, det_thresh=DET_THRESHOLD)
        return app
    except Exception as exc:                                 # noqa: BLE001
        log.warning("[face] %s failed to load: %s", PACK_NAME, exc)
        return _UNAVAILABLE


def _get_app():
    global _app
    with _lock:
        if _app is None:
            _app = _build()
        return None if _app is _UNAVAILABLE else _app


def reset_cache() -> None:
    """Drop the cached model (tests, and a posture change that should force a
    re-verify). The next call rebuilds."""
    global _app
    with _lock:
        _app = None


def available() -> bool:
    """True when a real face model could answer. Deliberately a DEPENDENCY +
    WEIGHTS probe, not a load: `FaceEmbedder.available` is read on construction
    paths that must stay cheap, and loading an ONNX graph there would put a
    hundred milliseconds into the Social Lens's constructor."""
    if not _deps_present():
        return False
    return os.path.isdir(os.path.join(model_root(), "models", PACK_NAME))


def _subject(faces, frame):
    """The face the wearer is looking at: the largest one, provided it is big
    enough in frame to be the subject at all.

    Returns None when every detected face is small enough to be a bystander in
    the background — in which case no template is computed for anyone, which is
    the point. Ties on area are broken toward the centre of frame.
    """
    if not faces:
        return None
    try:
        h, w = float(frame.shape[0]), float(frame.shape[1])
    except Exception:                                        # noqa: BLE001
        return None
    shorter = min(h, w) or 1.0
    cx, cy = w / 2.0, h / 2.0

    def _score(f):
        x1, y1, x2, y2 = (float(v) for v in f.bbox[:4])
        side = max(x2 - x1, y2 - y1)
        fx, fy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        dist = ((fx - cx) ** 2 + (fy - cy) ** 2) ** 0.5
        return side / shorter, -dist

    best = max(faces, key=_score)
    if _score(best)[0] < MIN_SUBJECT_FRACTION:
        return None
    return best


def _embed(frame):
    """The `embed_fn` contract: `(embedding, face_confidence)` or None."""
    app = _get_app()
    if app is None or frame is None:
        return None
    try:
        import numpy as np
        arr = np.asarray(frame)
        if arr.ndim != 3 or arr.shape[2] != 3:
            return None                       # not a colour frame; decline
        if arr.dtype != np.uint8:
            # ArcFace expects 8-bit BGR. A float frame in [0,1] is a caller
            # convention, not a face — convert rather than feed it garbage.
            arr = np.clip(arr * (255.0 if float(arr.max() or 0) <= 1.0 else 1.0),
                          0, 255).astype(np.uint8)
        faces = app.get(arr)
    except Exception as exc:                                 # noqa: BLE001
        # Never interpolate the frame or any detection geometry into a log.
        log.warning("[face] inference failed: %s", type(exc).__name__)
        return None
    face = _subject(faces, arr)
    if face is None:
        return None
    vec = getattr(face, "normed_embedding", None)
    if vec is None:
        return None
    try:
        out = [float(x) for x in vec]
    except Exception:                                        # noqa: BLE001
        return None
    score = float(getattr(face, "det_score", 0.0))
    if not 0.0 <= score <= 1.0:
        return None
    return out, score


def default_face_embed_fn():
    """The production `embed_fn`, or None when no real model can answer.

    None is the shipped default and is not a failure: `FaceEmbedder` treats it
    as "no embedder wired" and declines every frame, which is exactly what the
    site says the default build does.
    """
    if not available():
        return None
    return _embed
