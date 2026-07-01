"""Tests for FaceRecall contact index."""
import numpy as np
import pytest
from memoscape.face_recall.schema import ContactRecord
from memoscape.face_recall.index import ContactIndex
from memoscape.lie_lens.face_embed import cosine_similarity


def make_embedding(seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(512).astype(np.float32)
    return (v / (np.linalg.norm(v) + 1e-8)).tolist()


def make_contact(cid: str, seed: int = 42) -> ContactRecord:
    return ContactRecord(
        contact_id=cid,
        name=f"Person {cid}",
        embedding=make_embedding(seed),
    )


class TestContactIndex:
    def test_empty_index_returns_none(self):
        idx = ContactIndex()
        assert idx.search(make_embedding()) is None

    def test_exact_match_returns_high_confidence(self):
        idx = ContactIndex(threshold=0.60)
        c = make_contact("a", seed=1)
        idx.add(c)
        result = idx.search(c.embedding)
        assert result is not None
        assert result.confidence >= 0.99

    def test_different_embedding_no_match(self):
        idx = ContactIndex(threshold=0.60)
        c = make_contact("a", seed=1)
        idx.add(c)
        other = make_embedding(seed=999)
        # Very different random embeddings should score below threshold
        score = cosine_similarity(c.embedding, other)
        if score < 0.60:
            assert idx.search(other) is None

    def test_size_after_add(self):
        idx = ContactIndex()
        idx.add(make_contact("a"))
        idx.add(make_contact("b", seed=2))
        assert idx.size == 2

    def test_remove_contact(self):
        idx = ContactIndex()
        c = make_contact("a")
        idx.add(c)
        idx.remove("a")
        assert idx.size == 0

    def test_load_replaces_index(self):
        idx = ContactIndex()
        idx.add(make_contact("old"))
        idx.load([make_contact("new1", 10), make_contact("new2", 11)])
        assert idx.size == 2
        assert idx._contacts.get("old") is None

    def test_best_match_wins(self):
        idx = ContactIndex(threshold=0.50)
        c1 = make_contact("a", seed=1)
        c2 = make_contact("b", seed=2)
        idx.add(c1)
        idx.add(c2)
        # Searching with c1's exact embedding should match c1
        result = idx.search(c1.embedding)
        assert result is not None
        assert result.contact.contact_id == "a"

    def test_top_k_returns_list(self):
        idx = ContactIndex(threshold=0.50)
        for i in range(5):
            idx.add(make_contact(str(i), seed=i + 1))
        results = idx.search_top_k(make_contact("q", seed=1).embedding, k=3)
        assert isinstance(results, list)
        assert len(results) <= 3

    def test_top_k_sorted_by_confidence(self):
        idx = ContactIndex(threshold=0.50)
        for i in range(5):
            idx.add(make_contact(str(i), seed=i + 1))
        results = idx.search_top_k(make_contact("q", seed=1).embedding, k=5)
        if len(results) >= 2:
            assert results[0].confidence >= results[1].confidence
