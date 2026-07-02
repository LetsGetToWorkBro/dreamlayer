"""truth_lens/face_embed.py — Face detection and embedding extraction.

Simulates the on-device MobileFaceNet INT8 NPU pipeline.
In production this delegates to the real NPU inference layer;
here we provide a deterministic stub that is fully testable.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

EMBEDDING_DIM = 512
DETECTION_THRESHOLD = 0.50      # minimum face detection confidence


class FaceEmbedder:
    """Wraps face detection + embedding extraction.

    In production, `process_frame` calls the NPU model.
    The stub hashes the frame to produce a deterministic embedding
    so tests are reproducible without hardware.
    """

    def __init__(self, threshold: float = DETECTION_THRESHOLD):
        self.threshold = threshold
        self._call_count = 0

    def process_frame(self, frame: Optional[np.ndarray]) -> Optional["AUFrame"]:
        """Return an AUFrame with embedding if a face is detected, else None."""
        from .schema import AUFrame

        if frame is None:
            return None

        # Confidence heuristic: non-zero frame → face present
        face_confidence = float(np.mean(np.abs(frame))) if frame.size > 0 else 0.0
        if face_confidence < self.threshold:
            return None

        # Deterministic stub embedding from frame hash
        seed = int(np.sum(frame)) % (2 ** 31)
        rng = np.random.default_rng(seed)
        raw = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        embedding = (raw / (np.linalg.norm(raw) + 1e-8)).tolist()

        # Stub AU values (17 dims)
        au_values = rng.uniform(0.0, 0.3, 17).tolist()

        self._call_count += 1
        return AUFrame(
            au_values=au_values,
            face_confidence=min(face_confidence, 1.0),
            embedding=embedding,
        )

    @property
    def call_count(self) -> int:
        return self._call_count


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embedding vectors."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = (np.linalg.norm(va) * np.linalg.norm(vb)) + 1e-8
    return float(np.dot(va, vb) / denom)
