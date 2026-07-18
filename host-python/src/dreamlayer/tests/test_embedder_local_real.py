"""Local sentence-transformers embedder real-path coverage (issue #417): the
on-device provider (all-MiniLM-L6-v2, lazy-loaded, ~70 lines in
embedder_local.py) previously had only its mock-fallback path tested
(test_integration_seams_pr1.py::test_local_embedder_fallback). This adds the
real-path assertions the issue asks for: shape (384-d, not all zeros), the
normalize_embeddings=True contract (L2 norm ~= 1.0), and the semantic-ordering
detector (cos(cat, kitten) > cos(cat, thermodynamics)).

Needs sentence-transformers (importorskip), so the whole file skips when the
optional dep is absent -- exactly like test_chroma_store_real.py (#396),
test_vector_store_real.py (#428) and test_lance_store_real.py (#432) skip on
their own optional deps. Per the issue's own note, the first run downloads
~80MB from Hugging Face: this is a real-path test a contributor runs locally,
not something wired into the default CI job (it skips cleanly there).

Non-vacuity (the #396 lesson): a silent `except -> mock` degrade could make
these assertions pass for the wrong reason only if the mock ever produced a
384-d vector -- it can't (MockEmbeddingProvider.DIM == 32, so the shape
assertion alone already rules the mock out on any input), but every real-path
test also spies on `provider._mock.embed` and asserts it was never called,
mirroring how #396's spy asserted the vector store's linear fallback was
never called.
"""
import math

import pytest

from dreamlayer.memory.embeddings import cosine

pytest.importorskip("sentence_transformers")

from dreamlayer.memory import embedder_local  # noqa: E402  (after importorskip)
from dreamlayer.memory.embedder_local import LocalEmbeddingProvider  # noqa: E402


def _real_provider():
    """A LocalEmbeddingProvider with a genuinely loaded model, or a clean
    skip if the weights can't load (offline sandbox, first-run network
    failure) -- mirrors test_embedder_static.py's TestRealModel._real()."""
    emb = LocalEmbeddingProvider()
    if not emb.available or emb._get_model() is None:
        pytest.skip("sentence-transformers model could not be loaded")
    return emb


def _mock_spy(emb, monkeypatch):
    """Record any silent degrade to the mock -- the real-path tests must
    prove the sentence-transformers branch itself produced the answer, not a
    silent except->fallback rescuing it vacuously."""
    calls = []
    real = emb._mock.embed

    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)

    monkeypatch.setattr(emb._mock, "embed", spy)
    return calls


@pytest.mark.real_model
class TestRealPath:
    def test_shape_is_a_real_384d_vector(self, monkeypatch):
        emb = _real_provider()
        degraded = _mock_spy(emb, monkeypatch)
        v = emb.embed("the lease is due friday")
        assert degraded == []                        # real MiniLM path answered
        assert isinstance(emb._model, embedder_local.SentenceTransformer)
        assert len(v) == 384                          # all-MiniLM-L6-v2 width
        assert any(x != 0.0 for x in v)                # not an all-zero vector

    def test_output_is_l2_normalized(self, monkeypatch):
        emb = _real_provider()
        degraded = _mock_spy(emb, monkeypatch)
        v = emb.embed("the lease is due friday")
        assert degraded == []
        norm = math.sqrt(sum(x * x for x in v))
        assert norm == pytest.approx(1.0, abs=1e-4)    # normalize_embeddings=True

    def test_semantic_ordering_cat_kitten_beats_thermodynamics(self, monkeypatch):
        # The mock-detector: MockEmbeddingProvider is a 32-d bag of md5-hashed
        # whole words with no morphology/semantics signal, so it has no
        # principled way to rank "cat"/"kitten" over "cat"/"thermodynamics" --
        # this ordering can only come from the real model's semantics (and the
        # spy proves the mock never produced any of the three vectors).
        emb = _real_provider()
        degraded = _mock_spy(emb, monkeypatch)
        cat, kitten = emb.embed("cat"), emb.embed("kitten")
        thermo = emb.embed("thermodynamics")
        assert degraded == []
        assert cosine(cat, kitten) > cosine(cat, thermo)


class TestMockFallback:
    def test_forced_unavailable_degrades_to_mock_without_raising(self, monkeypatch):
        # Force the "sentence-transformers not installed" branch even though
        # the package IS installed in this environment (it must be, to reach
        # this importorskip-gated file): proves the _HAS_ST guard in
        # _get_model() degrades cleanly on its own, not only the try/except
        # around SentenceTransformer(...) a few lines below it.
        monkeypatch.setattr(embedder_local, "_HAS_ST", False)
        emb = LocalEmbeddingProvider()
        text = "the lease is due friday"
        v = emb.embed(text)                            # must not raise
        assert v == emb._mock.embed(text)              # exactly the mock's vector
        assert len(v) == 32                            # MockEmbeddingProvider.DIM
