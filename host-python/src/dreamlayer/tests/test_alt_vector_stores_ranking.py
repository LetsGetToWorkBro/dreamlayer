"""Correctness + privacy-residue pins for the ALTERNATE vector stores
(VectorStore / ChromaStore / LanceStore).

The reference is the brute-force blended-cosine ranking in
``vector_store.VectorStore._linear`` / ``retrieval.Retriever.search``:
over-fetch, blend ``0.5*sim + 0.5*confidence``, then ``sort(reverse=True)``.
Chroma and Lance must produce the SAME ordering.

The optional deps (chromadb / lancedb / sqlite-vec) are NOT installed in CI, so
every invariant here is pinned DEP-FREE with a faithful in-process fake backend
(the real backends are additionally exercised behind ``importorskip``). Each
test asserts the LEAK / WRONG-ORDER, so it fails when the fix is reverted.
"""
from __future__ import annotations

import math

import pytest

from dreamlayer.memory import chroma_store, lance_store
from dreamlayer.memory.chroma_store import ChromaStore
from dreamlayer.memory.lance_store import LanceStore
from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.embeddings import MockEmbeddingProvider
from dreamlayer.memory.retrieval import Retriever
from dreamlayer.memory.vector_store import VectorStore


# --------------------------------------------------------------------------- #
# Deterministic embedder: exact control over cosine similarity.                #
# query is always the unit vector (1, 0); a row's first coordinate IS its dot  #
# with the query (i.e. its cosine similarity, since every vector is unit).     #
# --------------------------------------------------------------------------- #
def _unit(dot: float) -> list[float]:
    return [dot, math.sqrt(max(0.0, 1.0 - dot * dot))]


class _FixedEmbedder:
    DIM = 2

    def __init__(self, table: dict[str, list[float]]):
        self._t = table

    def embed(self, text: str) -> list[float]:
        v = self._t[text]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


# --------------------------------------------------------------------------- #
# Faithful in-process fake of the lancedb query builder.                       #
# Default metric is L2 (lancedb's default) — the pre-fix code never requested  #
# cosine, so it lands here; the fixed code calls .metric("cosine").            #
# --------------------------------------------------------------------------- #
class _FakeLanceQuery:
    def __init__(self, data, qvec):
        self._data = data
        self._q = list(qvec)
        self._metric = "l2"
        self._limit = None

    def metric(self, m):
        self._metric = m
        return self

    def limit(self, n):
        self._limit = n
        return self

    def to_list(self):
        out = []
        for r in self._data:
            v = r["vector"]
            if self._metric == "cosine":
                dist = 1.0 - _dot(self._q, v)                 # cosine distance
            else:
                dist = sum((a - b) ** 2 for a, b in zip(self._q, v))  # squared L2
            row = dict(r)
            row["_distance"] = dist
            out.append(row)
        out.sort(key=lambda r: r["_distance"])                 # nearest first
        if self._limit is not None:
            out = out[:self._limit]
        return out


class _FakeLanceTable:
    def __init__(self, data):
        self._data = [dict(d) for d in data]

    def search(self, qvec):
        return _FakeLanceQuery(self._data, qvec)


class _FakeLanceConn:
    def __init__(self, store):
        self._store = store

    def create_table(self, name, data, mode="create"):
        self._store[name] = _FakeLanceTable(data)
        return self._store[name]

    def table_names(self):
        return list(self._store.keys())

    def drop_table(self, name):
        self._store.pop(name, None)


class _FakeLanceModule:
    def __init__(self):
        self._stores: dict[str, dict] = {}

    def connect(self, uri):
        return _FakeLanceConn(self._stores.setdefault(uri, {}))


def _install_fake_lance(monkeypatch):
    monkeypatch.setattr(lance_store, "_HAS_LANCE", True)
    monkeypatch.setattr(lance_store, "lancedb", _FakeLanceModule(), raising=False)


# A query builder that exposes NEITHER `.metric` nor `.distance_type` (older/odd
# lancedb builds), so the store cannot request cosine and must fall back to the
# linear scan. `.limit`/`.to_list` still run L2 so the REVERTED (no-fallback)
# code path is observable — it would return the wrong L2-as-cosine order.
class _FakeLanceQueryNoSetters:
    def __init__(self, data, qvec):
        self._data = data
        self._q = list(qvec)
        self._limit = None

    def limit(self, n):
        self._limit = n
        return self

    def to_list(self):
        out = []
        for r in self._data:
            row = dict(r)
            row["_distance"] = sum((a - b) ** 2 for a, b in zip(self._q, r["vector"]))
            out.append(row)
        out.sort(key=lambda r: r["_distance"])
        return out[:self._limit] if self._limit is not None else out


class _FakeLanceTableNoSetters(_FakeLanceTable):
    def search(self, qvec):
        return _FakeLanceQueryNoSetters(self._data, qvec)


class _FakeLanceConnNoSetters(_FakeLanceConn):
    def create_table(self, name, data, mode="create"):
        self._store[name] = _FakeLanceTableNoSetters(data)
        return self._store[name]


class _FakeLanceModuleNoSetters(_FakeLanceModule):
    def connect(self, uri):
        return _FakeLanceConnNoSetters(self._stores.setdefault(uri, {}))


def _install_fake_lance_no_setters(monkeypatch):
    monkeypatch.setattr(lance_store, "_HAS_LANCE", True)
    monkeypatch.setattr(lance_store, "lancedb", _FakeLanceModuleNoSetters(), raising=False)


def _seed(db, embedder, rows):
    """rows: list of (kind, summary, confidence). Store WITHOUT embeddings so
    both the store and the linear reference re-embed at query time (full
    precision, no float32 packing drift)."""
    ids = []
    for kind, summary, conf in rows:
        ids.append(db.add_memory(kind, summary, embedding=None, confidence=conf))
    return ids


# ===========================================================================
# Finding 1 (LanceStore): over-fetch + final blended-score re-sort.
# ===========================================================================
class TestLanceOverFetchAndResort:
    def test_blended_winner_survives_top_k_1(self, monkeypatch):
        # row-a is the LEAST similar of three but has the HIGHEST confidence, so
        # the 0.5*sim + 0.5*conf blend makes it the winner while raw distance
        # ranks it dead last. With top_k=1 the pre-fix `.limit(top_k)` fetches
        # only the single nearest neighbour (row-b) and never re-sorts, so the
        # blended winner is dropped before the blend is ever computed.
        emb = _FixedEmbedder({
            "q": _unit(1.0),
            "row-a": _unit(0.20), "row-b": _unit(0.95), "row-c": _unit(0.90),
        })
        db = MemoryDB(":memory:")
        _seed(db, emb, [("object", "row-a", 0.95),
                        ("object", "row-b", 0.10),
                        ("object", "row-c", 0.10)])
        _install_fake_lance(monkeypatch)
        got = LanceStore(db, embedder=emb, uri="mem://f1").search("q", top_k=1)
        # REVERT-FAILING: pre-fix returns row-b (nearest), never row-a.
        assert [m["summary"] for _, m in got] == ["row-a"]

    def test_full_ranking_matches_linear_reference(self, monkeypatch):
        emb = _FixedEmbedder({
            "q": _unit(1.0),
            "row-a": _unit(0.20), "row-b": _unit(0.95), "row-c": _unit(0.90),
        })
        db = MemoryDB(":memory:")
        _seed(db, emb, [("object", "row-a", 0.95),
                        ("object", "row-b", 0.10),
                        ("object", "row-c", 0.10)])
        _install_fake_lance(monkeypatch)
        got = LanceStore(db, embedder=emb, uri="mem://f1b").search("q", top_k=3)
        ref = Retriever(db, embedder=emb).search("q", top_k=3)
        # REVERT-FAILING: pre-fix returns raw-distance order [row-b,row-c,row-a].
        assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]
        assert [m["summary"] for _, m in got] == ["row-a", "row-b", "row-c"]


# ===========================================================================
# Finding 2 (LanceStore): cosine metric, not L2-read-as-cosine.
# ===========================================================================
class TestLanceCosineMetric:
    def test_l2_distance_is_not_read_as_cosine(self, monkeypatch):
        # row-p is MORE similar (dot .9) than row-q (dot .6) but less confident.
        # With the true cosine sim the blend makes row-q win; the pre-fix code
        # reads lancedb's default squared-L2 `_distance` as cosine (sim = 2*dot-1),
        # over-crediting the nearer row-p and flipping the order.
        emb = _FixedEmbedder({
            "q2": _unit(1.0), "row-p": _unit(0.90), "row-q": _unit(0.60),
        })
        db = MemoryDB(":memory:")
        _seed(db, emb, [("object", "row-p", 0.25), ("object", "row-q", 0.70)])
        _install_fake_lance(monkeypatch)
        got = LanceStore(db, embedder=emb, uri="mem://f2").search("q2", top_k=2)
        ref = Retriever(db, embedder=emb).search("q2", top_k=2)
        assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]
        # REVERT-FAILING: pre-fix (L2-as-cosine) ranks row-p first.
        assert got[0][1]["summary"] == "row-q"

    def test_no_cosine_setter_falls_back_to_linear_not_l2(self, monkeypatch):
        # A lancedb query builder exposing NEITHER `.metric` nor `.distance_type`
        # cannot be forced to cosine. The store must fall through to the linear
        # scan (as its comment promises) rather than silently run the query on
        # lancedb's default L2 and read `1 - _distance` as cosine — the exact bug
        # the cosine request closes. Same data as the cosine test: row-p is nearer
        # (dot .9) but less confident; under true cosine the blend makes row-q win,
        # under L2-as-cosine row-p wins (refute 2026-07-17).
        emb = _FixedEmbedder({
            "q2": _unit(1.0), "row-p": _unit(0.90), "row-q": _unit(0.60),
        })
        db = MemoryDB(":memory:")
        _seed(db, emb, [("object", "row-p", 0.25), ("object", "row-q", 0.70)])
        _install_fake_lance_no_setters(monkeypatch)
        got = LanceStore(db, embedder=emb, uri="mem://f2b").search("q2", top_k=2)
        ref = Retriever(db, embedder=emb).search("q2", top_k=2)
        assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]
        # REVERT-FAILING: without the linear fallback the query runs on default
        # L2 (read as cosine) and ranks the nearer-but-less-confident row-p first.
        assert got[0][1]["summary"] == "row-q"


# ===========================================================================
# Finding 3 (LanceStore): a stored confidence of 0.0 must stay 0.0.
# ===========================================================================
class TestLanceConfidenceZeroNotCoerced:
    def test_zero_confidence_not_inflated_to_half(self, monkeypatch):
        # Identical text -> identical embeddings, so confidence is the ONLY
        # discriminator. The pre-fix `(conf or 0.5)` coerces the 0.0 row up to
        # 0.5, floating it above the genuine 0.4 row.
        emb = _FixedEmbedder({"q3": _unit(1.0), "same": _unit(0.5)})
        db = MemoryDB(":memory:")
        _seed(db, emb, [("object", "same", 0.0), ("object", "same", 0.4)])
        _install_fake_lance(monkeypatch)
        got = LanceStore(db, embedder=emb, uri="mem://f3").search("q3", top_k=2)
        # REVERT-FAILING: pre-fix orders the 0.0 row first (0.0 -> 0.5).
        assert [m["confidence"] for _, m in got] == [0.4, 0.0]


# ===========================================================================
# Finding 4 (ChromaStore): forgetting must reach the PERSISTED collection even
# when THIS instance never searched (fresh process after restart). #415 keys
# vectors by stable memory_id, so evict() deletes exactly one vector (via
# _get_col, which opens the persisted collection); purge_all() drops the whole
# collection. The gap #415 left: _drop_collection early-returned when
# _client/_col were both None, so purge_all BEFORE any search left the on-disk
# collection intact — the lazy client-open in _drop_collection closes that.
# ===========================================================================
def _make_fake_chroma():
    disk: dict[str, dict] = {}   # path -> {name: collection}  (== on-disk state)

    class FakeCollection:
        def __init__(self, name):
            self.name = name
            self.items: dict = {}

        def upsert(self, ids, embeddings, metadatas):
            for i, e, meta in zip(ids, embeddings, metadatas):
                self.items[i] = (list(e), meta)

        def count(self):
            return len(self.items)

        def delete(self, ids):
            # single-vector forget: drop exactly the given ids (#415 keys by
            # stable memory_id, so evict removes one vector, not the collection)
            for i in ids:
                self.items.pop(i, None)

        def query(self, query_embeddings, n_results, where=None):
            q = query_embeddings[0]
            items = self.items.items()
            if where:                       # kind isolation lives in the query
                want = where.get("kind")
                items = [(i, ev) for i, ev in items if ev[1].get("kind") == want]
            scored = sorted((1.0 - _dot(q, e), i) for i, (e, _m) in items)
            scored = scored[:n_results]
            return {"ids": [[i for _d, i in scored]],
                    "distances": [[d for d, _i in scored]]}

    class FakePersistentClient:
        def __init__(self, path):
            self.path = path
            disk.setdefault(path, {})

        def get_or_create_collection(self, name, metadata=None):
            store = disk[self.path]
            store.setdefault(name, FakeCollection(name))
            return store[name]

        def delete_collection(self, name):
            disk[self.path].pop(name, None)

    class FakeModule:
        PersistentClient = FakePersistentClient
        EphemeralClient = None  # unused: these tests are persistent-path only

    return FakeModule(), disk


class TestChromaPersistentResidue:
    def test_forget_before_search_drops_on_disk_collection(self, monkeypatch, tmp_path):
        fake, disk = _make_fake_chroma()
        monkeypatch.setattr(chroma_store, "_HAS_CHROMA", True)
        monkeypatch.setattr(chroma_store, "chromadb", fake, raising=False)
        path = str(tmp_path / "chroma")
        emb = MockEmbeddingProvider()
        db = MemoryDB(":memory:")
        db.add_memory("scene", "the red bike by the door",
                      embedding=emb.embed("the red bike by the door"), confidence=0.6)

        # Session 1: a search persists the embedding into the on-disk collection.
        first = ChromaStore(db, embedder=emb, path=path, collection="mem")
        first.search("red bike", top_k=1)
        assert disk[path].get("mem") is not None
        assert disk[path]["mem"].items != {}          # embedding is on disk

        # Session 2 (fresh process after restart): never searched.
        second = ChromaStore(db, embedder=emb, path=path, collection="mem")
        assert second._client is None and second._col is None
        second.purge_all()                            # forget-before-search

        # REVERT-FAILING: pre-fix _drop_collection early-returned (both None),
        # leaving the forgotten embedding sitting in the persisted collection.
        assert "mem" not in disk[path], "persistent collection (embedding) survived forget"

    def test_evict_before_search_removes_only_that_vector_on_disk(self, monkeypatch, tmp_path):
        # #415 keys vectors by stable memory_id, so evict() deletes exactly the
        # forgotten vector — even on a fresh never-searched instance, which
        # opens the persisted collection (via _get_col) to remove that one id.
        # The kept memory's vector (and the collection) survive.
        fake, disk = _make_fake_chroma()
        monkeypatch.setattr(chroma_store, "_HAS_CHROMA", True)
        monkeypatch.setattr(chroma_store, "chromadb", fake, raising=False)
        path = str(tmp_path / "chroma")
        emb = MockEmbeddingProvider()
        db = MemoryDB(":memory:")
        keep = db.add_memory("scene", "keys on the counter",
                             embedding=emb.embed("keys on the counter"), confidence=0.6)
        drop = db.add_memory("scene", "the spare key under the mat",
                             embedding=emb.embed("the spare key under the mat"), confidence=0.6)
        ChromaStore(db, embedder=emb, path=path, collection="mem").search("keys", top_k=2)
        assert {str(keep), str(drop)} <= set(disk[path]["mem"].items)   # both persisted

        fresh = ChromaStore(db, embedder=emb, path=path, collection="mem")
        fresh.evict(drop)                             # forget one, before search
        # REVERT-FAILING: the forgotten vector is gone from the on-disk
        # collection; the kept one (and the collection) survive.
        assert str(drop) not in disk[path]["mem"].items
        assert str(keep) in disk[path]["mem"].items

    def test_realpath_matches_linear_reference(self, monkeypatch, tmp_path):
        # Dep-free pin that Chroma's real branch (over-fetch + blend + re-sort +
        # cosine + confidence None-check) already agrees with the linear ref.
        fake, _disk = _make_fake_chroma()
        monkeypatch.setattr(chroma_store, "_HAS_CHROMA", True)
        monkeypatch.setattr(chroma_store, "chromadb", fake, raising=False)
        emb = _FixedEmbedder({
            "q": _unit(1.0),
            "row-a": _unit(0.20), "row-b": _unit(0.95), "row-c": _unit(0.90),
        })
        db = MemoryDB(":memory:")
        _seed(db, emb, [("object", "row-a", 0.95),
                        ("object", "row-b", 0.0),      # 0.0 must stay 0.0
                        ("object", "row-c", 0.10)])
        got = ChromaStore(db, embedder=emb, path=str(tmp_path / "c"),
                          collection="mem").search("q", top_k=3)
        ref = Retriever(db, embedder=emb).search("q", top_k=3)
        assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]
        assert got[0][1]["summary"] == "row-a"


# ===========================================================================
# Finding 5 (VectorStore): evict / purge_all before the first search must NOT
# raise `no such table` (which would propagate and skip the bias discard).
# ===========================================================================
class _SpyBias:
    def __init__(self):
        self.discarded: list = []
        self.cleared = False

    def discard(self, kind, summary):
        self.discarded.append((kind, summary))

    def clear(self):
        self.cleared = True

    def save(self, directory):
        pass


class TestVectorStoreForgetBeforeSearch:
    def test_evict_and_purge_on_fresh_store_do_not_raise(self, monkeypatch):
        db = MemoryDB(":memory:")
        vs = VectorStore(db)
        # Simulate the extension loaded but no search yet -> memory_vec absent.
        monkeypatch.setattr(vs, "_ensure_loaded", lambda: True)
        assert vs._table_ready() is False                 # precondition
        # REVERT-FAILING: pre-fix both raise OperationalError('no such table').
        vs.evict(123)
        vs.purge_all()

    def test_purge_memory_before_search_still_discards_bias(self, monkeypatch, tmp_path):
        db = MemoryDB(":memory:")
        emb = MockEmbeddingProvider()
        vs = VectorStore(db, embedder=emb)
        monkeypatch.setattr(vs, "_ensure_loaded", lambda: True)
        bias = _SpyBias()
        r = Retriever(db, embedder=emb, vector_store=vs,
                      bias_store=bias, bias_dir=str(tmp_path))
        mid = db.add_memory("scene", "keys on the counter",
                            embedding=emb.embed("keys on the counter"), confidence=0.5)
        # REVERT-FAILING: pre-fix vs.evict raises inside purge_memory, so the
        # DB row is gone but the bias (content-hash fingerprint) is NEVER
        # discarded — a forget that leaves a rank-ghost behind.
        r.purge_memory(mid)
        assert db.memory(mid) is None
        assert bias.discarded == [("scene", "keys on the counter")]


# ===========================================================================
# Real-backend variants (skipped in CI; run when the optional dep is present).
# ===========================================================================
# ===========================================================================
# Finding 6 (ChromaStore): evict must survive a TRANSIENT _get_col() open
# failure. A PersistentClient that momentarily fails to open returns None from
# _get_col, and the pre-fix evict called it exactly once — one None skipped the
# single-vector delete, stranding the forgotten vector's bytes on disk (a
# forget-completeness gap). The fix retries the open a couple of times before
# giving up, so a transient failure still lands the delete.
# ===========================================================================
class TestChromaEvictRetriesTransientOpen:
    def test_get_col_failing_once_then_succeeding_still_deletes(self, monkeypatch, tmp_path):
        fake, disk = _make_fake_chroma()
        monkeypatch.setattr(chroma_store, "_HAS_CHROMA", True)
        monkeypatch.setattr(chroma_store, "chromadb", fake, raising=False)
        path = str(tmp_path / "chroma")
        emb = MockEmbeddingProvider()
        db = MemoryDB(":memory:")
        keep = db.add_memory("scene", "keys on the counter",
                             embedding=emb.embed("keys on the counter"), confidence=0.6)
        drop = db.add_memory("scene", "the spare key under the mat",
                             embedding=emb.embed("the spare key under the mat"), confidence=0.6)
        store = ChromaStore(db, embedder=emb, path=path, collection="mem")
        store.search("keys", top_k=2)                       # persist both vectors
        assert {str(keep), str(drop)} <= set(disk[path]["mem"].items)

        # A _get_col that returns None on its FIRST call (a transient
        # PersistentClient-open failure) then succeeds on the retry.
        real_get_col = store._get_col
        calls = {"n": 0}

        def flaky_get_col():
            calls["n"] += 1
            if calls["n"] == 1:
                return None                                 # transient open failure
            return real_get_col()

        monkeypatch.setattr(store, "_get_col", flaky_get_col)
        store.evict(drop)

        # REVERT-FAILING: pre-fix evict called _get_col ONCE, got None, and
        # skipped the delete — the retry is what makes the delete happen.
        assert calls["n"] >= 2                              # the retry engaged
        assert str(drop) not in disk[path]["mem"].items    # forgotten vector gone
        assert str(keep) in disk[path]["mem"].items        # kept vector survives


class TestRealLancePath:
    def setup_method(self):
        pytest.importorskip("lancedb")

    def test_realpath_reorders_and_matches_linear(self, tmp_path):
        emb = MockEmbeddingProvider()
        rows = [
            ("object", "remember to water the office plants on friday", 0.95),
            ("object", "the ferry to the island leaves at noon", 0.05),
            ("object", "the ferry to the island departs each morning", 0.05),
            ("object", "the island ferry schedule is posted at the dock", 0.05),
        ]
        db = MemoryDB(":memory:")
        for kind, summ, conf in rows:
            db.add_memory(kind, summ, embedding=emb.embed(summ), confidence=conf)
        store = LanceStore(db, embedder=emb, uri=str(tmp_path / "lance"), table="t395")
        q = "when does the island ferry leave"
        got = store.search(q, top_k=3)
        ref = VectorStore(db, embedder=MockEmbeddingProvider()).search(q, top_k=3)
        assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]
        assert got[0][1]["summary"] == rows[0][1]      # blended winner is top-1


class TestRealChromaPersistentResidue:
    def setup_method(self):
        pytest.importorskip("chromadb")

    def test_forget_before_search_drops_persistent_collection(self, tmp_path):
        import chromadb  # type: ignore
        emb = MockEmbeddingProvider()
        db = MemoryDB(":memory:")
        db.add_memory("scene", "the red bike by the door",
                      embedding=emb.embed("the red bike by the door"), confidence=0.6)
        path = str(tmp_path / "chroma")
        ChromaStore(db, embedder=emb, path=path, collection="resid").search("bike", top_k=1)
        # fresh session, never searched
        ChromaStore(db, embedder=emb, path=path, collection="resid").purge_all()
        client = chromadb.PersistentClient(path=path)
        cols = client.list_collections()
        names = [c if isinstance(c, str) else getattr(c, "name", c) for c in cols]
        assert "resid" not in names


# ===========================================================================
# Finding 5 (refute 2026-07-17): the alternate stores must honor HIDDEN_KINDS
# on a kind=None recall, exactly like Retriever — else a `stasis` bookmark (the
# wearer's verbatim unfinished sentence) surfaces in "what did I say about X"
# and the stores diverge from the linear reference.
# ===========================================================================
class TestAltStoresHideStasisKind:
    def _seeded(self):
        db = MemoryDB(":memory:")
        db.add_memory("stasis", "the wifi password is hunter2",
                      embedding=None, confidence=0.9)
        db.add_memory("object", "we set up the wifi at home",
                      embedding=None, confidence=0.5)
        return db

    def test_vector_store_hides_stasis_but_keeps_it_for_explicit_kind(self):
        emb = MockEmbeddingProvider()
        db = self._seeded()
        got = VectorStore(db, embedder=emb).search("wifi password", top_k=5)
        # REVERT-FAILING: without the HIDDEN_KINDS filter the stasis bookmark
        # (higher confidence) ranks first on a kind-less recall.
        assert "stasis" not in [m.get("kind") for _, m in got]
        ex = VectorStore(db, embedder=emb).search("wifi password",
                                                  kind="stasis", top_k=5)
        assert [m.get("kind") for _, m in ex] == ["stasis"]   # explicit still works

    def test_chroma_real_branch_hides_stasis(self, monkeypatch, tmp_path):
        fake, _disk = _make_fake_chroma()
        monkeypatch.setattr(chroma_store, "_HAS_CHROMA", True)
        monkeypatch.setattr(chroma_store, "chromadb", fake, raising=False)
        emb = MockEmbeddingProvider()
        db = self._seeded()
        got = ChromaStore(db, embedder=emb, path=str(tmp_path / "c")).search(
            "wifi password", top_k=5)
        assert "stasis" not in [m.get("kind") for _, m in got]   # REVERT-FAILING

    def test_lance_real_branch_hides_stasis(self, monkeypatch):
        _install_fake_lance(monkeypatch)
        emb = MockEmbeddingProvider()
        db = self._seeded()
        got = LanceStore(db, embedder=emb, uri="mem://hk").search(
            "wifi password", top_k=5)
        assert "stasis" not in [m.get("kind") for _, m in got]   # REVERT-FAILING
