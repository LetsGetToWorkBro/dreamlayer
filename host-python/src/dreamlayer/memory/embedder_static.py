"""Static (Model2Vec) embeddings — the missing middle rung of the ladder.

The embedder ladder used to jump straight from a real transformer
(sentence-transformers MiniLM, ~80 MB + PyTorch) to the lexical
HashingEmbeddingProvider — nothing semantic in between. A device that can't
carry PyTorch fell all the way back to lexical hashing, which never connects
*buy* and *purchase*.

Model2Vec (minishlab, MIT) closes that gap: it distills a sentence-transformer
into a **static** embedder — a token→vector lookup table with mean pooling, no
neural forward pass, no PyTorch, pure-CPU, ~30 MB, ~500× faster than the
teacher — at genuine (if slightly lower) semantic quality. It has a Rust port,
so the *same* tier can run on the phone/glasses, not just the Mac.

Same ADD-alongside contract as embedder_local.py: lazy import (extras group
`memory`), an `available` flag, an injectable model for tests, and graceful
fallback to the real lexical HashingEmbeddingProvider — never the md5 mock —
when the wheel or the model is missing.

    from dreamlayer.memory.embedder_static import StaticEmbeddingProvider
    emb = StaticEmbeddingProvider()          # potion until the dep is installed
    vec = emb.embed("snake plant on the sill")
"""
from __future__ import annotations

import logging
import math

from .embeddings import EmbeddingProvider, HashingEmbeddingProvider

log = logging.getLogger("dreamlayer.embedder_static")

try:  # optional dep — extras group `memory`
    from model2vec import StaticModel  # type: ignore
    _HAS_M2V = True
except Exception:
    StaticModel = None                  # type: ignore
    _HAS_M2V = False


class StaticEmbeddingProvider(EmbeddingProvider):
    """Distilled static embeddings via Model2Vec (potion-base-8M by default).

    Reads ``static_embedding_model`` off an optional config (duck-typed, like
    the other providers). Degrades to HashingEmbeddingProvider when model2vec
    isn't installed or the model can't load. Output is L2-normalized so it
    shares the cosine geometry the rest of the ladder assumes."""

    DEFAULT_MODEL = "minishlab/potion-base-8M"
    available = _HAS_M2V

    def __init__(self, config=None, model: str | None = None, _model=None):
        self._config = config
        self._model_name = (
            model
            or getattr(config, "static_embedding_model", "")
            or self.DEFAULT_MODEL
        )
        self._model = _model             # inject a loaded StaticModel in tests
        self._loaded = _model is not None
        self._fallback = HashingEmbeddingProvider()

    def _get_model(self):
        if self._loaded:
            return self._model
        self._loaded = True              # only attempt once
        if not _HAS_M2V:
            log.warning("[embedder_static] model2vec not installed; using hashing")
            return None
        try:
            self._model = StaticModel.from_pretrained(self._model_name)
        except Exception as exc:         # download / load failure
            log.error("[embedder_static] model load failed: %s; using hashing", exc)
            self._model = None
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._get_model()
        if model is None:
            return self._fallback.embed(text)
        try:
            vec = model.encode(text)
            out = [float(x) for x in vec]
            norm = math.sqrt(sum(v * v for v in out)) or 1.0
            return [v / norm for v in out]
        except Exception as exc:
            log.error("[embedder_static] encode failed: %s; using hashing", exc)
            return self._fallback.embed(text)
