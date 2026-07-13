"""P1-9: a cloud-embedder failure fails loud, never silently swaps dimension.

OpenAIEmbeddingProvider used to return the 32-d MockEmbeddingProvider vector on
any error, so a DB built in the 1536-d OpenAI space quietly took 32-d rows;
cosine()'s zip() then truncated to 32 and returned a garbage score with no
signal. Now: cosine refuses a dimension mismatch, and the provider degrades to
a same-dimension zero vector while recording the failure.
"""
from __future__ import annotations

from dreamlayer.memory.embeddings import cosine, OpenAIEmbeddingProvider


class _RaisingClient:
    class embeddings:
        @staticmethod
        def create(**_):
            raise RuntimeError("quota exceeded")


class _WrongWidthClient:
    class embeddings:
        @staticmethod
        def create(**_):
            return type("R", (), {"data": [type("D", (), {"embedding": [0.1] * 10})()]})


class TestCosineDimensionGuard:
    def test_mismatch_scores_zero_not_garbage(self):
        assert cosine([1.0] * 1536, [1.0] * 32) == 0.0     # no false match
        assert cosine([0.3] * 8, [0.3] * 8) > 0            # matched dims still score


class TestOpenAIDegrade:
    def _provider(self, client):
        errs = []
        p = OpenAIEmbeddingProvider(config=None,
                                    on_error=lambda e: errs.append(e))
        p._client = client                                 # skip real key/import
        return p, errs

    def test_api_error_degrades_to_zero_vector_of_correct_dim(self):
        p, errs = self._provider(_RaisingClient)
        vec = p.embed("anything")
        assert len(vec) == OpenAIEmbeddingProvider.DIM     # 1536, NOT 32
        assert set(vec) == {0.0}                           # zero, cosine 0
        assert len(errs) == 1                              # failure surfaced

    def test_wrong_width_response_is_refused(self):
        p, errs = self._provider(_WrongWidthClient)
        vec = p.embed("anything")
        assert len(vec) == OpenAIEmbeddingProvider.DIM     # not the 10-wide reply
        assert len(errs) == 1

    def test_no_client_degrades_not_mocks(self):
        # selected but unusable → same-dimension zero vector, never the 32-d mock
        p, errs = self._provider(None)
        p._get_client = lambda: None
        vec = p.embed("anything")
        assert len(vec) == OpenAIEmbeddingProvider.DIM
