"""sqlite-vec real-path semantic recall (issue #421): drive VectorStore.search()
through its INDEXED (vec0) branch — not the linear fallback — and pin the
behaviour the linear reference already guarantees.

VectorStore's linear fallback is covered elsewhere (test_alt_vector_stores_ranking
pins its blend/HIDDEN_KINDS/zero-confidence invariants dep-free). What has had
NO coverage is the vec0 indexed path: search() picks _search_indexed when the
extension loads, else _linear. Because a silent ``except -> _linear`` degrade
would make a real-path test pass VACUOUSLY on the fallback, every test here SPIES
on _linear and asserts it was never called — proof the vec0 branch itself
answered. Covered: the 0.5*sim + 0.5*conf blend (exact scores), kind= filtering,
the empty-DB early return ([]), the over-fetch/refill that keeps a stale (purged
but not evicted) row from starving the result below top_k, and the dead-row skip.

Needs sqlite-vec (importorskip). _search_indexed issues the ``k = ?`` form
(``... embedding MATCH ? AND k = ? ORDER BY distance``), not ``LIMIT ?`` —
the LIMIT form needs a SQLite new enough to push LIMIT down into a virtual
table, which older builds (e.g. 3.34.1) cannot do, and sqlite-vec's own error
for that shape ("A LIMIT or 'k = ?' constraint is required on vec0 knn
queries") makes the alternative explicit (#429). ``k = ?`` is a constraint
sqlite-vec evaluates itself rather than relying on the query planner's LIMIT
pushdown, so it runs the real indexed path on every SQLite this project
supports, 3.34.1 included — this module still probes the capability once and
skips cleanly on the rare box where sqlite-vec itself is unusable, rather than
let every test red-fail on a forced degrade.

The default MockEmbeddingProvider is a deterministic 32-d bag-of-word-hashes, so
rankings and blended scores are stable across runs; vectors match on shared whole
words, which is why the fixtures below share vocabulary with their queries.
"""
import sqlite3

import pytest

from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.embeddings import MockEmbeddingProvider, cosine
from dreamlayer.memory.vector_store import VectorStore

pytest.importorskip("sqlite_vec")
import sqlite_vec  # noqa: E402  (after importorskip)


def _vec0_knn_query_works() -> bool:
    """True when this box's SQLite/sqlite-vec pair can serve a vec0 knn query
    using the ``k = ?`` constraint form — the exact shape _search_indexed
    issues. Probes the SAME sqlite3 module the store uses (MemoryDB opens
    ``import sqlite3``), so a shim swapping in a different SQLite is honoured
    identically. Unlike the old ``LIMIT ?`` form, ``k = ?`` does not depend on
    the query planner pushing LIMIT into the virtual table, so this should
    succeed on essentially every sqlite-vec-capable SQLite — including 3.34.1
    (#429) — and only fails where sqlite-vec itself can't load/run at all."""
    try:
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            "CREATE VIRTUAL TABLE t USING vec0("
            "id integer primary key, embedding float[2] distance_metric=cosine)")
        conn.execute("INSERT INTO t(id, embedding) VALUES (?, ?)",
                     (1, sqlite_vec.serialize_float32([1.0, 0.0])))
        conn.execute(
            "SELECT id, distance FROM t WHERE embedding MATCH ? AND k = ? "
            "ORDER BY distance",
            (sqlite_vec.serialize_float32([1.0, 0.0]), 4)).fetchall()
        conn.close()
        return True
    except Exception:
        return False


if not _vec0_knn_query_works():
    pytest.skip(
        f"sqlite-vec indexed path unavailable on SQLite {sqlite3.sqlite_version} "
        "(k = ? knn query failed); VectorStore.search() degrades to linear "
        "here — nothing real to assert.",
        allow_module_level=True)


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


def _linear_spy(store, monkeypatch):
    """Record any degrade to the linear fallback. The real-path assertion is
    ``degraded == []`` — proof _search_indexed (the vec0 branch) answered."""
    calls = []
    real = store._linear
    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)
    monkeypatch.setattr(store, "_linear", spy)
    return calls


class TestIndexedPath:
    def test_obvious_nearest_ranks_first(self, monkeypatch):
        emb = MockEmbeddingProvider()
        store = VectorStore(_seeded(emb), embedder=emb)
        degraded = _linear_spy(store, monkeypatch)
        q = "where is my snake plant"
        out = store.search(q, top_k=3)
        assert degraded == []                        # vec0 branch, not linear
        assert store._indexed_ids                    # the index was populated
        assert len(out) == 3
        assert out[0][1]["summary"] == ROWS[0][1]
        scores = [s for s, _ in out]
        assert scores[0] > scores[1] > scores[2]
        # score = 0.5*sim + 0.5*conf; the vec0 table is distance_metric=cosine,
        # so sim = 1 - distance = cosine, and with uniform conf=0.5 every score
        # is exactly 0.5*cos + 0.25 (cos recomputed here from the embeddings).
        qv = emb.embed(q)
        for score, m in out:
            assert score == pytest.approx(
                0.5 * cosine(qv, emb.embed(m["summary"])) + 0.25, abs=1e-3)

    def test_blend_rewards_confidence(self, monkeypatch):
        # identical text -> identical embeddings and distances: confidence is
        # the ONLY thing that can separate the scores, by 0.5 * (0.95 - 0.05).
        emb = MockEmbeddingProvider()
        text = "the red kite festival is on saturday"
        db = _seeded(emb, [("object", text, 0.95), ("object", text, 0.05)])
        store = VectorStore(db, embedder=emb)
        degraded = _linear_spy(store, monkeypatch)
        out = store.search("kite festival", top_k=2)
        assert degraded == [] and len(out) == 2
        by_conf = {m["confidence"]: s for s, m in out}
        assert by_conf[0.95] > by_conf[0.05]
        assert by_conf[0.95] - by_conf[0.05] == pytest.approx(0.45, abs=1e-3)

    def test_zero_confidence_stays_zero(self, monkeypatch):
        # A stored confidence of 0.0 must NOT be coerced to the 0.5 default:
        # identical text makes confidence the only discriminator, so the 0.0 row
        # must rank BELOW the genuine 0.4 row (0.0 -> 0.5 would flip them).
        emb = MockEmbeddingProvider()
        text = "quarterly review meeting notes archived"
        db = _seeded(emb, [("object", text, 0.0), ("object", text, 0.4)])
        store = VectorStore(db, embedder=emb)
        degraded = _linear_spy(store, monkeypatch)
        out = store.search("review meeting", top_k=2)
        assert degraded == [] and len(out) == 2
        assert [m["confidence"] for _, m in out] == [0.4, 0.0]

    def test_kind_filter(self, monkeypatch):
        emb = MockEmbeddingProvider()
        store = VectorStore(_seeded(emb), embedder=emb)
        degraded = _linear_spy(store, monkeypatch)
        out = store.search("owed lease friday", kind="commitment", top_k=3)
        assert degraded == []
        assert len(out) == 2                          # only 2 commitments exist
        assert all(m["kind"] == "commitment" for _, m in out)
        assert out[0][1]["summary"] == ROWS[2][1]     # the lease, not the dentist

    def test_hidden_kind_excluded_on_kindless_recall(self, monkeypatch):
        # HIDDEN_KINDS (e.g. a `stasis` bookmark) must NOT surface on a kind=None
        # recall even when it is the higher-confidence, more-similar match —
        # mirroring the linear reference — yet stay reachable via explicit kind=.
        emb = MockEmbeddingProvider()
        db = MemoryDB(":memory:")
        db.add_memory("stasis", "the wifi password is hunter2",
                      embedding=emb.embed("the wifi password is hunter2"), confidence=0.9)
        db.add_memory("object", "we set up the wifi at home",
                      embedding=emb.embed("we set up the wifi at home"), confidence=0.5)
        store = VectorStore(db, embedder=emb)
        degraded = _linear_spy(store, monkeypatch)
        out = store.search("wifi password", top_k=5)
        assert degraded == []
        assert "stasis" not in [m.get("kind") for _, m in out]
        ex = store.search("wifi password", kind="stasis", top_k=5)
        assert [m.get("kind") for _, m in ex] == ["stasis"]

    def test_empty_db_returns_empty(self, monkeypatch):
        store = VectorStore(MemoryDB(":memory:"))
        degraded = _linear_spy(store, monkeypatch)
        assert store.search("anything", top_k=3) == []
        assert degraded == []                         # indexed early-return, not linear
        assert store._table_ready()                   # the vec0 table was built

    def test_blend_reorders_and_matches_linear(self, monkeypatch):
        # A genuine reorder the blend MUST perform and the over-fetch MUST feed:
        # `office plants` is the LEAST similar of the four to the query but has
        # the HIGHEST confidence, so 0.5*sim + 0.5*conf makes it the winner while
        # raw cosine distance ranks it dead last. The vec0 path must agree with
        # the linear reference on the ENTIRE ranking — order AND scores.
        emb = MockEmbeddingProvider()
        rows = [
            ("object", "remember to water the office plants on friday", 0.95),
            ("object", "the ferry to the island leaves at noon", 0.05),
            ("object", "the ferry to the island departs each morning", 0.05),
            ("object", "the island ferry schedule is posted at the dock", 0.05),
        ]
        db = _seeded(emb, rows)
        store = VectorStore(db, embedder=emb)
        degraded = _linear_spy(store, monkeypatch)
        q = "when does the island ferry leave"
        got = store.search(q, top_k=3)
        assert degraded == []                         # real vec0 path
        ref = VectorStore(db, embedder=MockEmbeddingProvider())._linear(q, None, 3)
        assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]
        assert [s for s, _ in got] == pytest.approx([s for s, _ in ref])
        assert got[0][1]["summary"] == rows[0][1]     # blended winner is top-1
        qv = emb.embed(q)
        raw_top = max(rows, key=lambda r: cosine(qv, emb.embed(r[1])))[1]
        assert raw_top != rows[0][1]                  # raw-distance top-1 differs
        assert cosine(qv, emb.embed(rows[0][1])) < cosine(qv, emb.embed(raw_top))


class TestStaleRowResilience:
    def test_stale_row_skipped_and_result_refilled_to_top_k(self, monkeypatch):
        # A memory purged from the DB but NOT evict()-ed leaves a live vector in
        # memory_vec. The over-fetch (LIMIT max(top_k*4,16), not top_k) means the
        # stale row's slot is refilled: search still returns top_k LIVE rows, and
        # the dead row is skipped (its DB row is gone) rather than counted. With
        # a naive LIMIT top_k the skipped top-ranked dead row would starve the
        # result to top_k-1.
        emb = MockEmbeddingProvider()
        db = _seeded(emb)
        store = VectorStore(db, embedder=emb)
        q = "where is my snake plant"
        first = store.search(q, top_k=3)              # build + populate the index
        victim_summary = first[0][1]["summary"]       # the top-ranked memory
        victim_id = next(m["id"] for m in db.memories()
                         if m["summary"] == victim_summary)
        db.purge_memory(victim_id)                    # gone from DB, still in vec0
        degraded = _linear_spy(store, monkeypatch)
        out = store.search(q, top_k=3)
        assert degraded == []                         # still the vec0 path
        assert len(out) == 3                          # refilled, not starved to 2
        summaries = [m["summary"] for _, m in out]
        assert victim_summary not in summaries        # dead row skipped
        live = {m["summary"] for m in db.memories()}
        assert all(s in live for s in summaries)      # every hit is a live row
