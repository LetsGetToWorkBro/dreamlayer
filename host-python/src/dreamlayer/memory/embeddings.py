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
    """Deterministic hash-based embeddings — no external deps, always works.

    A 32-d bag-of-word-hashes: a *test fixture*, not an intelligence tier. It
    only matches on shared whole words (no morphology, no subword signal), so a
    query and a memory that mean the same thing but spell it differently miss.
    Kept for tests that pin exact vectors; the real offline default is
    HashingEmbeddingProvider below."""
    DIM = 32

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.DIM
        for tok in text.lower().split():
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % self.DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _hashed_index(feature: str, dim: int) -> tuple[int, float]:
    """The signed hashing trick: map a string feature to a bucket and a ±1 sign
    from independent bytes of one blake2b digest. The sign hash makes colliding
    features cancel on average instead of always reinforcing, which keeps a
    fixed-width vector honest as the feature vocabulary grows."""
    h = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    idx = int.from_bytes(h[:4], "big") % dim
    sign = 1.0 if (h[4] & 1) else -1.0
    return idx, sign


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric runs — locale-free and dependency-free."""
    out, cur = [], []
    for ch in text.lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


class HashingEmbeddingProvider(EmbeddingProvider):
    """A real offline lexical embedder — no model, no deps, deterministic.

    Each text becomes an L2-normalized vector of hashed features: word unigrams
    plus character n-grams (3- and 4-grams over ``^word$``-padded tokens). The
    n-grams are what lift this above the mock — morphological variants share
    most of their grams, so *owe / owed / owes* and *water / watering* land
    close, and near-miss spellings still retrieve. It is still lexical, not
    semantic (it will not connect *buy* and *purchase*); the ladder in
    ``default_embedder`` prefers MiniLM/OpenAI whenever either is installed and
    only falls back to this. This is the offline default the system actually
    ships with when no model is present."""
    DIM = 512
    NGRAMS = (3, 4)
    WORD_WEIGHT = 1.0
    GRAM_WEIGHT = 0.5

    def __init__(self, dim: int | None = None):
        if dim is not None:
            self.DIM = dim

    def _accumulate(self, vec: list[float], feature: str, weight: float) -> None:
        idx, sign = _hashed_index(feature, self.DIM)
        vec[idx] += sign * weight

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.DIM
        for tok in _tokenize(text):
            self._accumulate(vec, "w:" + tok, self.WORD_WEIGHT)
            padded = "^" + tok + "$"
            for n in self.NGRAMS:
                if len(padded) <= n:
                    self._accumulate(vec, "g:" + padded, self.GRAM_WEIGHT)
                    continue
                for i in range(len(padded) - n + 1):
                    self._accumulate(vec, "g:" + padded[i:i + n], self.GRAM_WEIGHT)
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
# The default embedder ladder. Prefer real semantics whenever anything neural
# is installed: local MiniLM (384-d, offline, no key, but needs PyTorch) →
# Model2Vec static (256-d, offline, no key, no PyTorch, ~500× faster — the
# middle rung, ideal on a device that can't carry torch) → OpenAI (needs a
# key). With none, the offline default is the real lexical
# HashingEmbeddingProvider — NOT the 32-d md5 mock, which is only a test fixture.
# ---------------------------------------------------------------------------

def default_embedder(config=None) -> EmbeddingProvider:
    from .embedder_local import LocalEmbeddingProvider
    from .embedder_static import StaticEmbeddingProvider
    if LocalEmbeddingProvider.available:
        return LocalEmbeddingProvider(config)
    if StaticEmbeddingProvider.available:
        return StaticEmbeddingProvider(config)
    if getattr(config, "openai_api_key", "") or os.environ.get("OPENAI_API_KEY"):
        return OpenAIEmbeddingProvider(config)
    return HashingEmbeddingProvider()


def embedder_signature(embedder) -> str:
    """Stable id of the embedding space ("local:all-MiniLM-L6-v2", …).
    Vectors from different spaces must never share one index — the ANN
    layer rebuilds when this signature changes."""
    from .embedder_local import LocalEmbeddingProvider
    from .embedder_static import StaticEmbeddingProvider
    if isinstance(embedder, LocalEmbeddingProvider):
        return f"local:{embedder._model_name}"
    if isinstance(embedder, StaticEmbeddingProvider):
        return f"static:{embedder._model_name}"
    if isinstance(embedder, OpenAIEmbeddingProvider):
        model = (getattr(embedder._config, "embedding_model", "")
                 or embedder.DEFAULT_MODEL)
        return f"openai:{model}"
    if isinstance(embedder, HashingEmbeddingProvider):
        return f"hashing:{embedder.DIM}"
    if isinstance(embedder, MockEmbeddingProvider):
        return f"mock:{embedder.DIM}"
    return type(embedder).__name__
