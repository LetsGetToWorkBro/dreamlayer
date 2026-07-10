"""Retrieval quality regression — a fixed benchmark of memories + queries with
an ENFORCED precision@3 floor, so a change that quietly degrades recall fails
the build (not a skip).

The floor runs on HashingEmbeddingProvider — the real, dependency-free lexical
embedder that is the system's offline default — over two query families: a
literal set (queries share words with the memory) and a hard morphological set
(queries reword / inflect, e.g. "watering the plants" for "water the plant").
The mock's floor is kept as a low-water contrast, and the neural MiniLM test is
marked `real_model` so it runs for real in the real-models CI job."""
import pytest

from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.embeddings import (
    HashingEmbeddingProvider,
    MockEmbeddingProvider,
)
from dreamlayer.memory.embedder_local import LocalEmbeddingProvider
from dreamlayer.memory.retrieval import Retriever

# The memory set: (summary, a short needle that must appear in a top-3 hit).
BENCH = [
    ("snake plant on the windowsill, water every two weeks", "snake plant"),
    ("left the bike locked at the north rack on 4th and Alder", "bike"),
    ("Marcus is owed the signed lease by Friday", "Marcus"),
    ("Priya teaches ceramics, met at the Overpass show", "Priya"),
    ("the cafe on Pine street is cash only", "cash only"),
    ("dentist appointment on Tuesday at 3pm", "dentist"),
    ("passport is in the top drawer of the desk", "passport"),
    ("wifi password for the studio is bluewren", "wifi"),
    ("Mom's birthday is March 14th", "birthday"),
    ("parked the car on level 3 of the garage", "level 3"),
    ("the red wine from Rioja was 18 dollars last time", "Rioja"),
    ("gym membership renews on the first of the month", "gym"),
]

# Literal queries: share the memory's own words.
LITERAL = [
    ("how often water the plant", "snake plant"),
    ("where is my bike", "bike"),
    ("what do I owe Marcus", "Marcus"),
    ("who is Priya", "Priya"),
    ("cafe that takes cash", "cash only"),
    ("when is the dentist", "dentist"),
    ("where is my passport", "passport"),
    ("studio wifi password", "wifi"),
    ("when is mom's birthday", "birthday"),
    ("which level did I park", "level 3"),
    ("price of the rioja wine", "Rioja"),
    ("when does the gym renew", "gym"),
]

# Hard queries: morphological variants / rewordings that a whole-word bag of
# hashes (the mock) mostly misses but a char-ngram model recovers.
HARD = [
    ("watering the plants schedule", "snake plant"),
    ("locking up my bicycle spot", "bike"),
    ("what am I owing Marcus", "Marcus"),
    ("Priya's ceramics teaching", "Priya"),
    ("cafes accepting only cash payments", "cash only"),
    ("dental appointments this week", "dentist"),
    ("my passport's drawer", "passport"),
    ("studio wireless passwords", "wifi"),
    ("mom's birthdays date", "birthday"),
    ("garage parking levels", "level 3"),
    ("Riojan wine pricing", "Rioja"),
    ("gym renewals date", "gym"),
]


def _precision_at_3(embedder, queries) -> float:
    db = MemoryDB()
    r = Retriever(db, embedder)
    for summary, _needle in BENCH:
        mid = db.add_memory("note", summary, embedding=embedder.embed(summary))
        r.index_memory(mid, embedder.embed(summary))
    hits = 0
    for query, needle in queries:
        top3 = r.search(query, top_k=3)
        if any(needle.lower() in m["summary"].lower() for _s, m in top3):
            hits += 1
    return hits / len(queries)


class TestRetrievalQuality:
    def test_hashing_embedder_precision_floor(self):
        # The real offline default. Measured 1.00 on both families today; the
        # floor is set with headroom so a collision/normalization regression
        # fails loudly without flaking on a single unlucky hash.
        combined = LITERAL + HARD
        p = _precision_at_3(HashingEmbeddingProvider(), combined)
        assert p >= 0.83, f"hashing precision@3 regressed to {p:.2f}"

    def test_hashing_beats_mock_on_morphology(self):
        # The whole reason the offline default is the hashing model, not the
        # 32-d bag: it survives inflection. This is the guard that we never
        # regress the default back to a whole-word matcher.
        hashing = _precision_at_3(HashingEmbeddingProvider(), HARD)
        mock = _precision_at_3(MockEmbeddingProvider(), HARD)
        assert hashing >= mock + 0.25, (
            f"hashing ({hashing:.2f}) no longer clears mock ({mock:.2f}) "
            f"on morphological queries by the expected margin")

    def test_mock_embedder_stays_a_weak_fixture(self):
        # The mock is a fixture, not a tier; its literal precision is a sanity
        # low-water mark (it should still get the easy, word-sharing queries).
        p = _precision_at_3(MockEmbeddingProvider(), LITERAL)
        assert p >= 0.5, f"mock precision@3 regressed to {p:.2f}"

    @pytest.mark.real_model
    def test_local_embedder_beats_hashing_when_installed(self):
        # Runs for real in the real-models CI job (MiniLM installed). Neural
        # semantics should clear the lexical floor on the hard set outright.
        if not LocalEmbeddingProvider.available:
            pytest.skip("sentence-transformers not installed")
        local = _precision_at_3(LocalEmbeddingProvider(), LITERAL + HARD)
        assert local >= 0.9, f"local precision@3 regressed to {local:.2f}"
