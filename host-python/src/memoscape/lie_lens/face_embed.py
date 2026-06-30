"""lie_lens/face_embed.py — Face detection + 512-d embedding.

Simulates the MobileFaceNet INT8 NPU pipeline. In production this calls
the Halo NPU via the bridge; in tests a deterministic mock is used.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

EMBEDDING_DIM = 512
FACE_CONFIDENCE_THRESHOLD = 0.65


@dataclass
class FaceDetection:
    embedding: np.ndarray           # 512-d float32 unit vector
    detection_confidence: float     # 0-1
    bbox: tuple[int, int, int, int] # x, y, w, h in pixels


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two unit-norm vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class FaceEmbedder:
    """Runs face detection + embedding on a camera frame.

    In production: calls npu.run('MobileFaceNet_INT8', frame).
    In tests:      inject a mock via the `npu_fn` parameter.
    """

    def __init__(self, npu_fn=None,
                 threshold: float = FACE_CONFIDENCE_THRESHOLD):
        self._npu = npu_fn or self._mock_npu
        self.threshold = threshold

    def detect(self, frame: Optional[np.ndarray]) -> Optional[FaceDetection]:
        """Return FaceDetection or None if no confident face found."""
        if frame is None:
            return None
        result = self._npu(frame)
        if result is None:
            return None
        conf = result.get("confidence", 0.0)
        if conf < self.threshold:
            return None
        emb = np.array(result["embedding"], dtype=np.float32)
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return FaceDetection(
            embedding=emb,
            detection_confidence=conf,
            bbox=result.get("bbox", (0, 0, 100, 100)),
        )

    def match_contacts(self,
                       embedding: np.ndarray,
                       contacts: dict[str, np.ndarray],
                       threshold: float = 0.65) -> Optional[tuple[str, float]]:
        """Match embedding against contact dict → (contact_id, score) or None."""
        best_id, best_score = None, 0.0
        for cid, cemb in contacts.items():
            score = cosine_similarity(embedding, cemb)
            if score > best_score:
                best_score, best_id = score, cid
        if best_id and best_score >= threshold:
            return best_id, best_score
        return None

    @staticmethod
    def _mock_npu(frame: np.ndarray) -> Optional[dict]:
        """Deterministic mock: returns a face if frame mean > 0.1."""
        if frame.mean() < 0.1:
            return None
        rng = np.random.default_rng(seed=int(frame.mean() * 1000) % 2**31)
        emb = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        return {
            "embedding": emb,
            "confidence": float(min(frame.mean() + 0.4, 1.0)),
            "bbox": (20, 20, 80, 80),
        }
