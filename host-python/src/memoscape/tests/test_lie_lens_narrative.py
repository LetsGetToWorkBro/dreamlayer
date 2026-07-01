"""Tests for the NarrativeStore."""
import pytest
from memoscape.lie_lens.narrative_store import NarrativeStore
from memoscape.lie_lens.schema import (
    AUFrame, ProsodyFrame, LinguisticFrame,
)


def make_au(val=0.3):
    return AUFrame(au_values=[val] * 17, face_confidence=0.9)


def make_prosody(jitter=1.0, shimmer=1.5):
    return ProsodyFrame(
        pitch_mean_hz=180.0, pitch_variance=50.0,
        jitter_pct=jitter, shimmer_pct=shimmer,
        hesitation_rate=0.5, pause_ratio=0.25,
        speech_rate_norm=1.0, energy_db=-20.0,
    )


def make_linguistic(hedging=0.1):
    return LinguisticFrame(
        hedging_rate=hedging, first_person_rate=0.05,
        complexity_score=0.4, negation_rate=0.1,
        word_count=42,
    )


class TestNarrativeStore:
    def test_get_baseline_none_initially(self):
        ns = NarrativeStore()
        assert ns.get_baseline("alice") is None

    def test_update_baseline_creates_entry(self):
        ns = NarrativeStore()
        bl = ns.update_baseline(
            "alice", au=make_au(), prosody=make_prosody(),
            linguistic=make_linguistic(),
        )
        assert bl.contact_id == "alice"
        assert bl.sample_count == 1

    def test_update_baseline_increments_count(self):
        ns = NarrativeStore()
        for _ in range(5):
            ns.update_baseline(
                "alice", au=make_au(), prosody=make_prosody(),
                linguistic=make_linguistic(),
            )
        assert ns.get_baseline("alice").sample_count == 5

    def test_calibrated_after_10_samples(self):
        ns = NarrativeStore()
        for _ in range(10):
            ns.update_baseline(
                "alice", au=make_au(), prosody=make_prosody(),
                linguistic=make_linguistic(),
            )
        assert ns.get_baseline("alice").is_calibrated

    def test_not_calibrated_before_10(self):
        ns = NarrativeStore()
        for _ in range(9):
            ns.update_baseline(
                "alice", au=make_au(), prosody=make_prosody(),
                linguistic=make_linguistic(),
            )
        assert not ns.get_baseline("alice").is_calibrated

    def test_partial_update_does_not_persist(self):
        # All three channels are required before a baseline sample counts
        ns = NarrativeStore()
        ns.update_baseline("bob", au=make_au(), prosody=None, linguistic=None)
        assert ns.get_baseline("bob") is None

    def test_log_anomaly_stores_entry(self):
        ns = NarrativeStore()
        ns.log_anomaly("alice", 0.8, "voice_stress", user_label="confirmed")
        logs = ns.get_anomaly_log("alice")
        assert len(logs) == 1
        assert logs[0]["user_label"] == "confirmed"

    def test_get_anomaly_log_empty_initially(self):
        ns = NarrativeStore()
        assert ns.get_anomaly_log("nobody") == []

    def test_contact_count(self):
        ns = NarrativeStore()
        for name in ("alice", "bob"):
            for _ in range(3):
                ns.update_baseline(
                    name, au=make_au(), prosody=make_prosody(),
                    linguistic=make_linguistic(),
                )
        assert ns.contact_count() == 2
