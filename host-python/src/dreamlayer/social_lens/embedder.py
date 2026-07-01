"""social_lens/embedder.py — 512-d face embedding (shared with truth_lens)."""
from __future__ import annotations
from typing import Optional
import numpy as np
from dreamlayer.truth_lens.face_embed import FaceEmbedder, cosine_similarity

EMBEDDING_DIM = 512
MIN_FACE_CONFIDENCE = 0.50


def embed_frame(frame: Optional[np.ndarray],
                embedder=None) -> tuple[Optional[list[float]], float]:
    if embedder is None:
        embedder = FaceEmbedder(threshold=MIN_FACE_CONFIDENCE)
    au = embedder.process_frame(frame)
    if au is None or au.embedding is None:
        return None, 0.0
    return au.embedding, au.face_confidence


__all__ = ["FaceEmbedder", "cosine_similarity", "embed_frame", "EMBEDDING_DIM"]
