"""Model2Vec static-embedding tier: fallback contract, ladder wiring, and a
guarded real-model check. The fake-model tests need no download; the real one
skips when model2vec or its weights are unavailable (e.g. offline CI)."""
import math

import pytest

from dreamlayer.memory import embeddings as E
from dreamlayer.memory.embedder_static import StaticEmbeddingProvider
from dreamlayer.memory.embeddings import HashingEmbeddingProvider


class _FakeModel:
    """Stand-in for model2vec StaticModel: deterministic per-text vector."""
    def __init__(self, dim=8): self.dim = dim
    def encode(self, text):
        import numpy as np
        h = abs(hash(text))
        return np.array([((h >> i) & 0xFF) / 255.0 for i in range(self.dim)],
                        dtype="float32")


class TestFallbackContract:
    def test_absent_falls_back_to_hashing_not_mock(self):
        # no injected model, dep may be absent → hashing, byte-identical
        emb = StaticEmbeddingProvider(_model=None)
        emb._loaded = True               # skip the load attempt → force fallback
        emb._model = None
        got = emb.embed("buy the milk")
        assert got == HashingEmbeddingProvider().embed("buy the milk")

    def test_injected_model_output_is_l2_normalized(self):
        emb = StaticEmbeddingProvider(_model=_FakeModel())
        v = emb.embed("snake plant")
        assert len(v) == 8
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)

    def test_encode_error_degrades_to_hashing(self):
        class _Boom:
            def encode(self, t): raise RuntimeError("nope")
        emb = StaticEmbeddingProvider(_model=_Boom())
        assert emb.embed("x") == HashingEmbeddingProvider().embed("x")


class TestLadderWiring:
    def test_static_sits_between_local_and_hashing(self, monkeypatch):
        # Local off, static on → ladder picks static
        monkeypatch.setattr(
            "dreamlayer.memory.embedder_local.LocalEmbeddingProvider.available",
            False)
        monkeypatch.setattr(StaticEmbeddingProvider, "available", True)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        chosen = E.default_embedder(config=None)
        assert isinstance(chosen, StaticEmbeddingProvider)

    def test_local_still_wins_when_present(self, monkeypatch):
        monkeypatch.setattr(
            "dreamlayer.memory.embedder_local.LocalEmbeddingProvider.available",
            True)
        monkeypatch.setattr(StaticEmbeddingProvider, "available", True)
        from dreamlayer.memory.embedder_local import LocalEmbeddingProvider
        assert isinstance(E.default_embedder(None), LocalEmbeddingProvider)

    def test_hashing_when_neither_present(self, monkeypatch):
        monkeypatch.setattr(
            "dreamlayer.memory.embedder_local.LocalEmbeddingProvider.available",
            False)
        monkeypatch.setattr(StaticEmbeddingProvider, "available", False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert isinstance(E.default_embedder(None), HashingEmbeddingProvider)

    def test_signature(self):
        emb = StaticEmbeddingProvider(_model=_FakeModel())
        assert E.embedder_signature(emb) == f"static:{emb._model_name}"


@pytest.mark.real_model
class TestRealModel:
    """Runs in the real-models CI job (deselected by default), where model2vec
    + weights are available."""

    def _real(self):
        pytest.importorskip("model2vec")
        emb = StaticEmbeddingProvider()
        if not emb.available or emb._get_model() is None:
            pytest.skip("model2vec weights not available")
        return emb

    def test_dim_and_normalized(self):
        emb = self._real()
        v = emb.embed("a snake plant on the windowsill")
        assert len(v) >= 128
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-5)

    def test_more_semantic_than_hashing(self):
        # the whole point of the tier: static connects synonyms the lexical
        # hasher can't ("purchase" vs "buy" share no n-grams)
        emb = self._real()
        cos = E.cosine
        s = cos(emb.embed("please buy the groceries"),
                emb.embed("we need to purchase food"))
        h = HashingEmbeddingProvider()
        hsim = cos(h.embed("please buy the groceries"),
                   h.embed("we need to purchase food"))
        assert s > hsim
