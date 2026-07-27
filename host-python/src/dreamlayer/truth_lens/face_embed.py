"""truth_lens/face_embed.py — Face detection and embedding extraction.

THERE IS NO FACE MODEL HERE. This module is the seam where an on-device
MobileFaceNet-class embedder would be wired; nothing is wired yet. Read the
next three paragraphs before touching it.

The stub that used to live here produced a 512-d gaussian seeded by the frame's
PIXEL SUM. That has two consequences, both measured:

  * Two visually unrelated frames with the same pixel sum get the BYTE-IDENTICAL
    embedding -> cosine 1.0 -> clears the 0.65 match threshold and the top-2
    margin -> a stranger is announced to the wearer as a named contact at
    "100% match". The per-pair collision rate for a 96x96x3 frame is 1 in
    ~43,800 (sigma of the pixel sum is ~12,226; 1/(2*sigma*sqrt(pi))). At 30 fps
    against 100 enrolled contacts that is a false name every few seconds, and it
    is GUARANTEED for any two frames that are permutations, reflections, or
    uniform fields of each other.
  * Two photos of the SAME person differing by one brightness step score ~0.00
    cosine (measured mean -0.0002 over 160 pairs; 0 of 160 cleared 0.65). So the
    intended function never worked at all, and its only successful output was a
    confident wrong identification.

`face_confidence` was the same kind of fiction: `mean(abs(frame))` is 0-255 for a
uint8 frame and was compared against a 0.50 threshold, so ANY non-black image --
including a 1x1 white pixel -- asserted a face at 100%.

So both now FAIL CLOSED. `process_frame` returns None unless a real embedder is
injected. `brain_social.py` already refuses to wire this stub to the dossier,
with the words "wiring that to a dossier would fabricate identity - the exact
dishonesty this project refuses"; this module now holds itself to that too. An
honest "I don't know them yet" already exists on every consumer path.

Tests that need determinism can pass an explicit `embed_fn`; that is the same
injection seam a real model will use, so nothing has to change when one arrives.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:                       # AUFrame is imported lazily at call time
    from .schema import AUFrame         # (real import lives inside process_frame)

EMBEDDING_DIM = 512
DETECTION_THRESHOLD = 0.50      # minimum face detection confidence


class FaceEmbedder:
    """The face-embedding seam. Declines unless a real embedder is injected.

    `embed_fn(frame) -> (embedding, face_confidence) | None` is the hole a real
    on-device model plugs into. With no `embed_fn`, `process_frame` returns None
    and every consumer takes its existing honest "no face / I don't know them"
    path. See the module docstring for why guessing is not an option here.
    """

    def __init__(self, threshold: float = DETECTION_THRESHOLD, embed_fn=None):
        self.threshold = threshold
        self._embed_fn = embed_fn
        self._call_count = 0

    @property
    def available(self) -> bool:
        """True only when a real embedder is wired. Callers that want to explain
        the gap to the wearer ("face recall needs the vision pack") read this
        instead of inferring capability from a None return."""
        return self._embed_fn is not None

    def process_frame(self, frame: Optional[np.ndarray]) -> Optional["AUFrame"]:
        """Return an AUFrame with an embedding, or None when we cannot know.

        None is returned for: no frame, no wired embedder, a frame the embedder
        declines, and a detection below `threshold`. A caller must never read a
        None as "not a contact" -- it means "no answer", which is why the cards
        downstream say "I don't know them yet" rather than "not in your
        contacts"."""
        from .schema import AUFrame

        if frame is None or self._embed_fn is None:
            return None
        if getattr(frame, "size", 0) == 0:
            return None
        # A frame carrying NaN/Inf used to raise out of `int(np.sum(frame))` --
        # ValueError / OverflowError from a method documented never to raise.
        try:
            if not bool(np.isfinite(frame).all()):
                return None
        except TypeError:                       # non-numeric dtype
            return None

        try:
            out = self._embed_fn(frame)
        except Exception:                       # noqa: BLE001 - a seam never raises
            return None
        if not out:
            return None
        embedding, face_confidence = out
        face_confidence = float(face_confidence)
        # A real detector reports a PROBABILITY. Anything outside [0,1] is a
        # miscalibrated backend, not a very certain one -- decline rather than
        # clamp a 255 down to a confident 1.0, which is exactly how the pixel-mean
        # stub came to assert a face in every non-black image.
        if not 0.0 <= face_confidence <= 1.0:
            return None
        if face_confidence < self.threshold:
            return None
        if embedding is None or len(embedding) != EMBEDDING_DIM:
            return None

        self._call_count += 1
        return AUFrame(
            au_values=[0.0] * 17,               # no AU model: see au_backends.py
            face_confidence=face_confidence,
            embedding=list(embedding),
        )

    @property
    def call_count(self) -> int:
        return self._call_count


# --------------------------------------------------------------------------
# A TEST DOUBLE. Not a face model, and never wired in production.
# --------------------------------------------------------------------------

def deterministic_embed_fn(threshold: float = 0.9):
    """An `embed_fn` for tests: recalls the SAME image, never confuses two.

    The suite has a lot of downstream logic to exercise -- introductions, notes,
    the dossier, recall cards -- and all of it needs *an* embedder. This is that
    embedder, and it is honest about being a double:

      * the embedding is seeded by a cryptographic digest of the frame's BYTES,
        so two frames match if and only if they are byte-identical. That is the
        property the old pixel-sum stub lacked: equal-sum-different-content frames
        collided, which is how a stranger got named as a contact at 100%.
      * it makes NO claim to recognise a person across two photographs. It
        cannot; nothing here can. A test that needs cross-photo recall is
        testing a face model, and there isn't one.

    Production gets `embed_fn=None` and declines. See the module docstring.
    """
    import hashlib

    def _embed(frame):
        # Decline a frame with nothing in it. Not detection -- a double cannot
        # detect -- but it keeps "an all-dark frame yields no face" true, which is
        # a property the callers legitimately rely on.
        arr = np.asarray(frame, dtype=np.float64)
        scale = 255.0 if arr.max() > 1.0 else 1.0
        if float(arr.std()) < 1e-6 and float(arr.mean()) / scale < 0.05:
            return None
        digest = hashlib.blake2b(np.ascontiguousarray(frame).tobytes(),
                                 digest_size=8).digest()
        rng = np.random.default_rng(int.from_bytes(digest, "big"))
        raw = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        return (raw / (np.linalg.norm(raw) + 1e-8)).tolist(), float(threshold)

    return _embed


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embedding vectors."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = (np.linalg.norm(va) * np.linalg.norm(vb)) + 1e-8
    return float(np.dot(va, vb) / denom)
