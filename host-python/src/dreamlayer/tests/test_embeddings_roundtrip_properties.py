"""Property-based coverage for the embedding storage/compare primitives that
"forget is ANN-safe" and honest recall depend on (audit 2026-07-14 Section 7,
quick-win #3).

Two pure functions carry the load:

  * pack_embedding / unpack_embedding — the on-disk format. Embeddings persist
    as packed float32 BLOBs; unpack_embedding must also read legacy JSON-text
    rows and already-decoded lists (lazy migration). A round-trip that loses or
    reorders values would silently corrupt every recall.

  * cosine — refuses to compare vectors of different dimension (returns 0.0),
    so a dimension-mixed row (e.g. a stray 32-d vector against a 1536-d query)
    can never false-match. That guard is what stops a forgotten-then-reindexed
    or wrong-space vector from surfacing.

Run standalone:
    python -m pytest tests/test_embeddings_roundtrip_properties.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json

from hypothesis import assume, given, strategies as st

from dreamlayer.memory.embeddings import (
    HashingEmbeddingProvider,
    cosine,
    pack_embedding,
    unpack_embedding,
)

# width=32 keeps every generated value exactly representable as float32, so the
# pack (float32) -> unpack round-trip is bit-exact, not merely close.
finite32 = st.floats(allow_nan=False, allow_infinity=False, width=32)
vectors = st.lists(finite32, max_size=64)


@given(vectors)
def test_pack_unpack_roundtrip_is_exact(vec):
    """unpack(pack(vec)) reproduces the vector value-for-value (float32-exact)."""
    assert unpack_embedding(pack_embedding(vec)) == vec


@given(vectors)
def test_pack_unpack_preserves_length_and_order(vec):
    out = unpack_embedding(pack_embedding(vec))
    assert len(out) == len(vec)
    # order is load-bearing: dimension i of the query must meet dimension i of
    # the row. Check element-wise, not just as a set.
    assert all(a == b for a, b in zip(out, vec))


def test_unpack_none_stays_none():
    assert unpack_embedding(None) is None


@given(vectors)
def test_unpack_reads_legacy_json_text_rows(vec):
    """Pre-existing rows stored as JSON text must still decode (lazy migration)."""
    assert unpack_embedding(json.dumps(vec)) == vec


@given(vectors)
def test_unpack_passthrough_of_decoded_list_returns_a_copy(vec):
    out = unpack_embedding(vec)
    assert out == vec
    assert out is not vec        # unpack returns list(raw), never the same object


@given(
    st.lists(finite32, min_size=1, max_size=32),
    st.lists(finite32, min_size=1, max_size=32),
)
def test_cosine_refuses_dimension_mismatch(a, b):
    """Different-length vectors never false-match: cosine returns exactly 0.0."""
    assume(len(a) != len(b))
    assert cosine(a, b) == 0.0


@given(st.lists(finite32, min_size=1, max_size=16))
def test_cosine_is_symmetric_for_equal_dimensions(a):
    b = [x * 0.5 for x in a]
    assert cosine(a, b) == cosine(b, a)


@given(st.text(min_size=1, max_size=40))
def test_hashing_embedding_is_unit_norm_and_self_matches(text):
    """The offline default embedder yields L2-normalized vectors, so a memory
    matches itself with cosine ~= 1 (or a zero vector for tokenless input) —
    the property recall relies on."""
    vec = HashingEmbeddingProvider().embed(text)
    norm_sq = sum(x * x for x in vec)
    self_sim = cosine(vec, vec)
    if norm_sq == 0.0:                       # text had no alphanumeric tokens
        assert self_sim == 0.0
    else:
        assert abs(norm_sq - 1.0) < 1e-6
        assert abs(self_sim - 1.0) < 1e-6
