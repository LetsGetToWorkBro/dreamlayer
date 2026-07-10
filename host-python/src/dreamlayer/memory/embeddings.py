from __future__ import annotations
import hashlib
import logging
import math
import os
from abc import ABC, abstractmethod

log = logging.getLogger("dreamlayer.embeddings")


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]: ...


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic hash-based embeddings — no external deps, always works."""
    DIM = 32

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.DIM
        for tok in text.lower().split():
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % self.DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Real semantic embeddings via OpenAI text-embedding-3-small.

    Lazy-imports openai so the package remains optional. Falls back to
    MockEmbeddingProvider on any error (missing key, network, quota).

    Parameters
    ----------
    config : Config | None
        If provided, reads openai_api_key and embedding_model from it.
        Environment variable OPENAI_API_KEY is used as fallback.
    """
    DEFAULT_MODEL = "text-embedding-3-small"

    def __init__(self, config=None):
        self._config  = config
        self._client  = None
        self._mock    = MockEmbeddingProvider()  # fallback

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import openai  # type: ignore
        except ImportError:
            log.warning("[embeddings] openai not installed; using mock")
            return None

        api_key = (
            getattr(self._config, "openai_api_key", "") or
            os.environ.get("OPENAI_API_KEY", "")
        )
        if not api_key:
            log.warning("[embeddings] OPENAI_API_KEY not set; using mock")
            return None

        timeout = getattr(self._config, "llm_timeout_s", 4.0)
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout)
        return self._client

    def embed(self, text: str) -> list[float]:
        client = self._get_client()
        if client is None:
            return self._mock.embed(text)

        model = (
            getattr(self._config, "embedding_model", self.DEFAULT_MODEL)
            or self.DEFAULT_MODEL
        )
        try:
            resp = client.embeddings.create(input=text, model=model)
            return resp.data[0].embedding
        except Exception as exc:
            log.error("[embeddings] OpenAI call failed: %s; using mock", exc)
            return self._mock.embed(text)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Storage format: embeddings persist as packed float32 BLOBs, not JSON text.
# A 1536-d vector is ~6 KB as JSON and 6 bytes/dim of parse cost on every
# read; packed it's 4 bytes/dim and one frombuffer call. unpack reads BOTH
# formats so pre-existing JSON-text rows keep working (lazy migration).
# ---------------------------------------------------------------------------

def pack_embedding(vec) -> bytes:
    import numpy as np
    return np.asarray(vec, dtype=np.float32).tobytes()


def unpack_embedding(raw) -> list[float] | None:
    """Decode a stored embedding: float32 BLOB (current), JSON text
    (legacy rows), or an already-decoded list. None stays None."""
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        import numpy as np
        return np.frombuffer(raw, dtype=np.float32).tolist()
    if isinstance(raw, str):
        import json
        return json.loads(raw)
    return list(raw)


# ---------------------------------------------------------------------------
# The default embedder ladder. 32-d md5 hashes are a test fixture, not an
# intelligence tier — prefer real semantics whenever anything real is
# installed: local MiniLM (384-d, offline, no key) → OpenAI (needs a key)
# → mock, last.
# ---------------------------------------------------------------------------

def default_embedder(config=None) -> EmbeddingProvider:
    from .embedder_local import LocalEmbeddingProvider
    if LocalEmbeddingProvider.available:
        return LocalEmbeddingProvider(config)
    if getattr(config, "openai_api_key", "") or os.environ.get("OPENAI_API_KEY"):
        return OpenAIEmbeddingProvider(config)
    return MockEmbeddingProvider()


def embedder_signature(embedder) -> str:
    """Stable id of the embedding space ("local:all-MiniLM-L6-v2", …).
    Vectors from different spaces must never share one index — the ANN
    layer rebuilds when this signature changes."""
    from .embedder_local import LocalEmbeddingProvider
    if isinstance(embedder, LocalEmbeddingProvider):
        return f"local:{embedder._model_name}"
    if isinstance(embedder, OpenAIEmbeddingProvider):
        model = (getattr(embedder._config, "embedding_model", "")
                 or embedder.DEFAULT_MODEL)
        return f"openai:{model}"
    if isinstance(embedder, MockEmbeddingProvider):
        return f"mock:{embedder.DIM}"
    return type(embedder).__name__
