"""Local sentence-transformers embeddings — an on-device EmbeddingProvider.

ADD-alongside: this is a new sibling to embeddings.py. It never modifies the
existing MockEmbeddingProvider / OpenAIEmbeddingProvider. It lazy-imports
sentence-transformers so the package stays optional (extras group `memory`),
and falls back to the deterministic MockEmbeddingProvider on any failure —
same contract as OpenAIEmbeddingProvider.

    from dreamlayer.memory.embedder_local import LocalEmbeddingProvider
    emb = LocalEmbeddingProvider()          # uses mock until the dep is installed
    vec = emb.embed("snake plant on the sill")
"""
from __future__ import annotations
import logging

from .embeddings import EmbeddingProvider, MockEmbeddingProvider

log = logging.getLogger("dreamlayer.embedder_local")

try:  # optional dep — extras group `memory`
    from sentence_transformers import SentenceTransformer  # type: ignore
    _HAS_ST = True
except ImportError:
    _HAS_ST = False


class LocalEmbeddingProvider(EmbeddingProvider):
    """80MB local model (all-MiniLM-L6-v2 by default), no API call, no key.

    Reads `embedding_model` off an optional config (duck-typed, like
    OpenAIEmbeddingProvider). Degrades to MockEmbeddingProvider when
    sentence-transformers isn't installed or the model can't load.
    """
    DEFAULT_MODEL = "all-MiniLM-L6-v2"
    available = _HAS_ST

    def __init__(self, config=None, model: str | None = None):
        self._config = config
        self._model_name = (
            model
            or getattr(config, "local_embedding_model", "")
            or self.DEFAULT_MODEL
        )
        self._model = None
        self._mock = MockEmbeddingProvider()

    def _get_model(self):
        if self._model is not None:
            return self._model
        if not _HAS_ST:
            log.warning("[embedder_local] sentence-transformers not installed; using mock")
            return None
        try:
            self._model = SentenceTransformer(self._model_name)
        except Exception as exc:  # model download / load failure
            log.error("[embedder_local] model load failed: %s; using mock", exc)
            return None
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._get_model()
        if model is None:
            return self._mock.embed(text)
        try:
            vec = model.encode(text, normalize_embeddings=True)
            return [float(x) for x in vec]
        except Exception as exc:
            log.error("[embedder_local] encode failed: %s; using mock", exc)
            return self._mock.embed(text)
