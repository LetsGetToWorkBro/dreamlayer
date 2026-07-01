"""face_recall/embedder.py — 512-d face embedding extraction.

Reuses the FaceEmbedder from lie_lens for consistent embeddings
across both modules. FaceRecall and LieLens share the same
MobileFaceNet INT8 NPU model and embedding space, so a contact
enrolled via FaceRecall is immediately compatible with LieLens.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

# Re-export from lie_lens to keep a single embedding implementation
from memoscape.lie_lens.face_embed import FaceEmbedder, cosine_similarity

EMBEDDING_DIM = 512
MIN_FACE_CONFIDENCE = 0.50


def embed_frame(frame: Optional[np.ndarray],
                embedder: Optional[FaceEmbedder] = None
                ) -> tuple[Optional[list[float]], float]:
    """Extract a 512-d embedding from a camera frame.

    Returns
    -------
    (embedding, face_confidence)
        embedding is None if no face detected.
    """
    if embedder is None:
        embedder = FaceEmbedder(threshold=MIN_FACE_CONFIDENCE)
    au = embedder.process_frame(frame)
    if au is None or au.embedding is None:
        return None, 0.0
    return au.embedding, au.face_confidence


__all__ = ["FaceEmbedder", "cosine_similarity", "embed_frame", "EMBEDDING_DIM"]
