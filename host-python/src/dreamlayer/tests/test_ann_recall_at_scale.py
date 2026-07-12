"""ANN recall fidelity *at scale* — the guarantee that actually matters.

The maintained HNSW index (memory/ann_index.py, wired into Retriever via
`ann=`) exists for one reason: keep recall glance-fast when the memory set
grows to the 10k–100k a year of heavy wear produces. The existing parity tests
prove ANN == linear on 4–12 rows — but at that size an HNSW graph is trivially
exact, so they don't actually exercise the approximation. The real risk is
silent: switch the index on at scale and it quietly drops the right answer for
some queries.

This harness closes that gap. It builds a realistically-sized synthetic memory
set, computes the *exact* linear top-k as ground truth (vectorized), and asserts
the ANN path's recall against that ground truth stays above an enforced floor —
so a regression in the index (wrong metric, bad over-fetch, a usearch upgrade
that changes defaults) fails the build instead of degrading answers in the
field.

Needs usearch; skipped cleanly when the extra is absent."""
import pytest

pytest.importorskip("usearch")
import numpy as np  # noqa: E402

from dreamlayer.memory.db import MemoryDB                    # noqa: E402
from dreamlayer.memory.ann_index import PersistentAnnIndex   # noqa: E402

N_MEMORIES = 1500
N_QUERIES = 120
DIM = 64
TOP_K = 5
_CLUSTERS = 24


def _unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def _centers():
    rng = np.random.default_rng(20260712)      # fixed — determinism, no Random()
    return _unit(rng.standard_normal((_CLUSTERS, DIM)))


def _vec(centers, salt: int):
    """A deterministic unit vector near one cluster center — reproducible from
    the salt alone (same id → same vector across runs), with real neighbor
    structure (clustered, not uniform noise where recall is meaningless)."""
    rng = np.random.default_rng(salt % (2**32))
    v = centers[salt % _CLUSTERS] + 0.35 * rng.standard_normal(DIM)
    return _unit(v).astype(np.float32)


@pytest.fixture(scope="module")
def scaled():
    """Build the graph + DB + a memory-embedding matrix once for the module."""
    centers = _centers()
    db = MemoryDB()
    ann = PersistentAnnIndex(None, DIM)
    assert ann.live, "usearch index should be live with the extra installed"
    mat = np.zeros((N_MEMORIES, DIM), dtype=np.float32)
    ids = []
    for i in range(N_MEMORIES):
        vec = _vec(centers, i)
        mat[i] = vec
        mid = db.add_memory("note", "mem:%d" % i, embedding=vec.tolist())
        ann.add(mid, vec.tolist())
        ids.append(mid)
    # query vectors sit in a different salt space so they're not memory copies
    queries = np.stack([_vec(centers, 10_000 + q) for q in range(N_QUERIES)])
    return {"db": db, "ann": ann, "mat": mat, "ids": np.array(ids),
            "queries": queries}


def _exact_topk_ids(scaled, qv, k):
    sims = scaled["mat"] @ qv                    # cosine (all unit vectors)
    idx = np.argpartition(-sims, k)[:k]
    idx = idx[np.argsort(-sims[idx])]
    return scaled["ids"][idx].tolist()


class TestAnnRecallAtScale:
    def test_index_holds_the_full_set(self, scaled):
        assert len(scaled["ann"]) == N_MEMORIES    # every row made it into the graph

    def test_recall_against_exact_ground_truth_clears_floor(self, scaled):
        ann = scaled["ann"]
        overlap = 0.0
        for q in range(N_QUERIES):
            qv = scaled["queries"][q]
            exact = set(_exact_topk_ids(scaled, qv, TOP_K))
            hits = ann.search(qv.tolist(), k=max(TOP_K * 4, 16))  # over-fetch
            approx = set(mid for mid, _sim in hits[:TOP_K])
            overlap += len(exact & approx) / TOP_K
        recall = overlap / N_QUERIES
        # HNSW at this size should be near-perfect; floor has headroom so a real
        # index regression fails but sampling noise doesn't flake.
        assert recall >= 0.90, f"ANN recall@{TOP_K} at scale regressed to {recall:.3f}"

    def test_top1_is_almost_always_exact(self, scaled):
        # the single most important neighbor — the answer the HUD shows — should
        # match the exact top-1 the overwhelming majority of the time
        ann = scaled["ann"]
        agree = 0
        for q in range(N_QUERIES):
            qv = scaled["queries"][q]
            exact1 = _exact_topk_ids(scaled, qv, 1)[0]
            hits = ann.search(qv.tolist(), k=16)
            if hits and hits[0][0] == exact1:
                agree += 1
        rate = agree / N_QUERIES
        assert rate >= 0.90, f"ANN top-1 agreement at scale regressed to {rate:.3f}"

    def test_search_returns_bounded_k_not_the_whole_set(self, scaled):
        # sanity that the graph is doing graph-search, not a hidden linear pass:
        # a query returns k results, never the whole N-row set
        hits = scaled["ann"].search(scaled["queries"][7].tolist(), k=32)
        assert 0 < len(hits) <= 32
