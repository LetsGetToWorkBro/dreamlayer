"""LanceDB real-path semantic recall (issue #416): ranking, the
0.5*sim + 0.5*confidence blend, kind filtering, the empty-DB early return, the
HIDDEN_KINDS filter on a kind-less recall, and the linear fallback. Mirrors
test_chroma_store_real.py (#282/#396) for the sibling LanceStore.

Needs lancedb (importorskip), so the whole file skips when the optional dep is
absent. LanceStore.search rebuilds its table on every call (mode="overwrite"),
so a per-test uri under tmp_path needs no pre-seeded state and no cross-test
leak. The default MockEmbeddingProvider is deterministic, so ranking and score
assertions are stable across runs.

LanceStore keeps no persistent collection handle (unlike ChromaStore._col), so
the ONLY proof the real Lance branch — not a silent except->fallback — produced
the answer is the fallback spy: every real-path test asserts ``degraded == []``.
Without it a broken Lance path would make these tests pass vacuously via the
linear scan (issue #396's lesson). The two lance_store.py fixes these scores pin
(cosine metric so ``1 - _distance`` is真 cosine, not lancedb's default L2; and a
stored ``confidence=0.0`` staying 0.0 rather than being coerced to 0.5) landed
on main in #418; this test guards them on the REAL backend."""
import pytest

from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.embeddings import MockEmbeddingProvider, cosine
from dreamlayer.memory.lance_store import LanceStore
from dreamlayer.memory.vector_store import VectorStore

lancedb = pytest.importorskip("lancedb")

ROWS = [
    ("object", "snake plant on the windowsill water every two weeks", 0.5),
    ("object", "bike locked at the north rack on 4th and Alder", 0.5),
    ("commitment", "Marcus is owed the signed lease by Friday", 0.5),
    ("object", "passport is in the top drawer of the desk", 0.5),
    ("commitment", "call the dentist about Tuesday at 3pm", 0.5),
]


def _seeded(emb, rows=ROWS):
    db = MemoryDB(":memory:")
    for kind, summary, conf in rows:
        db.add_memory(kind, summary, embedding=emb.embed(summary), confidence=conf)
    return db


def _fallback_spy(store, monkeypatch):
    """Record any silent degrade to the linear fallback — the real-path tests
    must prove the Lance branch itself produced the answer."""
    calls = []
    real = store._fallback.search

    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)

    monkeypatch.setattr(store._fallback, "search", spy)
    return calls


def _store(db, tmp_path, name="mem"):
    # a distinct on-disk uri per store; mode="overwrite" rebuilds every search
    return LanceStore(db, uri=str(tmp_path / name))


class TestRealPath:
    def test_obvious_nearest_ranks_first(self, monkeypatch, tmp_path):
        emb = MockEmbeddingProvider()
        store = _store(_seeded(emb), tmp_path)
        degraded = _fallback_spy(store, monkeypatch)
        q = "where is my snake plant"
        out = store.search(q, top_k=3)
        assert degraded == []                        # real lance path answered
        assert len(out) == 3
        assert out[0][1]["summary"] == ROWS[0][1]
        scores = [s for s, _ in out]
        assert scores[0] > scores[1] > scores[2]
        # score = 0.5*sim + 0.5*conf; the table is queried in cosine space, so
        # sim = 1 - cosine_distance = cos, and with uniform conf=0.5 every score
        # is exactly 0.5*cos + 0.25 (cos recomputed here).
        qv = emb.embed(q)
        for score, m in out:
            assert score == pytest.approx(
                0.5 * cosine(qv, emb.embed(m["summary"])) + 0.25, abs=1e-3)

    def test_blend_rewards_confidence(self, monkeypatch, tmp_path):
        # identical text -> identical embeddings and distances: confidence is
        # the ONLY thing that can separate the scores, by 0.5 * (0.95 - 0.05)
        emb = MockEmbeddingProvider()
        text = "the red kite festival is on saturday"
        db = _seeded(emb, [("object", text, 0.95), ("object", text, 0.05)])
        store = _store(db, tmp_path)
        degraded = _fallback_spy(store, monkeypatch)
        out = store.search("kite festival", top_k=2)
        assert degraded == [] and len(out) == 2
        by_conf = {m["confidence"]: s for s, m in out}
        assert by_conf[0.95] > by_conf[0.05]         # the confident one wins
        assert by_conf[0.95] - by_conf[0.05] == pytest.approx(0.45, abs=1e-3)

    def test_kind_filter(self, monkeypatch, tmp_path):
        emb = MockEmbeddingProvider()
        store = _store(_seeded(emb), tmp_path)
        degraded = _fallback_spy(store, monkeypatch)
        out = store.search("owed lease friday", kind="commitment", top_k=3)
        assert degraded == []
        assert len(out) == 2                         # only 2 commitments exist
        assert all(m["kind"] == "commitment" for _, m in out)
        assert out[0][1]["summary"] == ROWS[2][1]    # the lease, not the dentist

    def test_empty_db_returns_empty(self, monkeypatch, tmp_path):
        # LanceStore returns [] from its early rows-empty check BEFORE it ever
        # connects to lancedb, so there is no persistent handle to assert on
        # (as ChromaStore's _col). The spy is the proof: an empty [] with NO
        # fallback call means the real lance branch's early return fired, not a
        # silent degrade masquerading as "empty".
        store = _store(MemoryDB(":memory:"), tmp_path)
        degraded = _fallback_spy(store, monkeypatch)
        assert store.search("anything", top_k=3) == []
        assert degraded == []                        # early return on the lance path

    def test_blend_reorders_and_matches_linear(self, monkeypatch, tmp_path):
        # The #395/#416 core symptom AND the ordering guarantee in one scenario.
        # `plants` is the LEAST similar of the four to the query but has the
        # HIGHEST confidence, so the 0.5*sim + 0.5*conf blend makes it the
        # winner while raw cosine distance ranks it dead last. This forces a
        # genuine reorder that:
        #   - the re-score/re-sort MUST perform (without it, lance's raw-distance
        #     order wins and top-1 is the most-similar/low-conf row),
        #   - the full-candidate over-fetch MUST feed (with .limit(top_k) the
        #     blended winner sits beyond the distance-truncated window and is
        #     dropped before the blend ever sees it).
        # So the real lance path must agree with the linear fallback on the
        # ENTIRE ranking — order and scores — not merely the top-1.
        emb = MockEmbeddingProvider()
        rows = [
            ("object", "remember to water the office plants on friday", 0.95),
            ("object", "the ferry to the island leaves at noon", 0.05),
            ("object", "the ferry to the island departs each morning", 0.05),
            ("object", "the island ferry schedule is posted at the dock", 0.05),
        ]
        db = _seeded(emb, rows)
        store = _store(db, tmp_path)
        degraded = _fallback_spy(store, monkeypatch)
        q = "when does the island ferry leave"
        got = store.search(q, top_k=3)
        assert degraded == []                        # real lance path answered
        ref = VectorStore(db, embedder=MockEmbeddingProvider()).search(q, top_k=3)
        assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]
        assert [s for s, _ in got] == pytest.approx([s for s, _ in ref], abs=1e-3)
        # the blend genuinely reordered: the confident-but-least-similar memory
        # is top-1, NOT the row lance's raw distance would rank first.
        assert got[0][1]["summary"] == rows[0][1]
        qv = emb.embed(q)
        raw_top = max(rows, key=lambda r: cosine(qv, emb.embed(r[1])))[1]
        assert raw_top != rows[0][1]                 # raw top-1 is a DIFFERENT row
        assert cosine(qv, emb.embed(rows[0][1])) < cosine(qv, emb.embed(raw_top))

    def test_zero_confidence_not_coerced_to_half(self, monkeypatch, tmp_path):
        # Invariant mirrored from test_alt_vector_stores_ranking.py: an explicit
        # confidence=0.0 must stay 0.0, not be coerced to 0.5 by a `conf or 0.5`.
        # Identical text -> identical similarity, so confidence is the ONLY
        # discriminator: the genuine 0.4 row must outrank the 0.0 row (which the
        # coercion bug would float up to 0.5 and rank first).
        emb = MockEmbeddingProvider()
        text = "the lantern parade winds through the old town"
        db = _seeded(emb, [("object", text, 0.0), ("object", text, 0.4)])
        store = _store(db, tmp_path)
        degraded = _fallback_spy(store, monkeypatch)
        out = store.search("lantern parade", top_k=2)
        assert degraded == [] and len(out) == 2      # real lance path answered
        assert [m["confidence"] for _, m in out] == [0.4, 0.0]

    def test_hidden_kind_excluded_on_kindless_recall(self, monkeypatch, tmp_path):
        # Invariant mirrored from test_alt_vector_stores_ranking.py: a kind=None
        # recall hides HIDDEN_KINDS (a `stasis` bookmark), exactly like the
        # linear reference — even though stasis is the higher-confidence row and
        # would otherwise rank first. An explicit kind="stasis" still returns it.
        emb = MockEmbeddingProvider()
        db = _seeded(emb, [
            ("stasis", "the wifi password is hunter2", 0.9),
            ("object", "we set up the wifi at home", 0.5),
        ])
        store = _store(db, tmp_path)
        degraded = _fallback_spy(store, monkeypatch)
        out = store.search("wifi password", top_k=5)
        assert degraded == []                        # real lance path answered
        assert "stasis" not in [m["kind"] for _, m in out]
        ex = store.search("wifi password", kind="stasis", top_k=5)
        assert [m["kind"] for _, m in ex] == ["stasis"]   # explicit still works


class TestLinearFallback:
    def test_query_failure_degrades_to_linear(self, monkeypatch, tmp_path):
        # resilience: a broken lance query must not lose recall — the answer
        # comes back via VectorStore's linear scan, sorted by blended score, so
        # the confident memory takes the top rank despite being the LESS similar
        # of the two (the blend flips the rank here).
        emb = MockEmbeddingProvider()
        conf_txt, sim_txt = "kite festival", "kite festival saturday picnic"
        db = _seeded(emb, [("event", conf_txt, 0.95), ("event", sim_txt, 0.05)])
        store = _store(db, tmp_path)
        degraded = _fallback_spy(store, monkeypatch)
        q = "kite festival saturday"

        def boom(*a, **k):
            raise RuntimeError("lance down")

        # break the real lance path (connect happens inside search's try block);
        # the linear fallback never touches lancedb, so it still answers.
        monkeypatch.setattr(lancedb, "connect", boom)
        got = store.search(q, top_k=2)
        assert degraded != []                        # the fallback DID answer
        ref = VectorStore(db, embedder=MockEmbeddingProvider()).search(q, top_k=2)
        assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]
        assert [s for s, _ in got] == pytest.approx([s for s, _ in ref], abs=1e-3)
        assert got[0][1]["summary"] == conf_txt
        qv = emb.embed(q)
        assert cosine(qv, emb.embed(conf_txt)) < cosine(qv, emb.embed(sim_txt))
