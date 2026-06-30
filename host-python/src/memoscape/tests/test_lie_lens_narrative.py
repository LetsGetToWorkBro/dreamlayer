"""Tests for LieLens NarrativeStore."""
import numpy as np
import pytest
from memoscape.lie_lens.narrative_store import NarrativeStore
from memoscape.lie_lens.schema import (
    ContactBaseline, AUFrame, ProsodyFrame,
)
from memoscape.lie_lens.linguistic import extract_linguistic_features


def make_baseline(cid="alice", samples=30):
    return ContactBaseline(
        contact_id=cid,
        au_mean=[0.15] * 17,
        au_std=[0.05] * 17,
        prosody_pitch_mean=180.0,
        prosody_pitch_std=20.0,
        prosody_jitter_mean=0.5,
        prosody_shimmer_mean=1.0,
        linguistic_hedge_mean=0.08,
        linguistic_fp_mean=0.12,
        sample_count=samples,
    )


class TestNarrativeStore:
    def test_get_missing_baseline_returns_none(self):
        store = NarrativeStore()
        assert store.get_baseline("nobody") is None

    def test_save_and_get_baseline(self):
        store = NarrativeStore()
        b = make_baseline()
        store.save_baseline(b)
        assert store.get_baseline("alice") is b

    def test_incremental_update_creates_baseline(self):
        store = NarrativeStore()
        au = AUFrame(aus=[0.2] * 17, micro_exp_label="neutral",
                     micro_exp_confidence=0.6)
        pf = ProsodyFrame(pitch_mean_hz=180, pitch_variance=50,
                          jitter_pct=0.5, shimmer_pct=1.0,
                          hesitation_rate=0.3, energy_db=-20,
                          speech_rate_norm=1.0)
        lf = extract_linguistic_features("I went to the store.")
        b = store.update_baseline_incremental("bob", au, pf, lf)
        assert b.sample_count == 1
        assert store.get_baseline("bob") is not None

    def test_incremental_update_increments_count(self):
        store = NarrativeStore()
        for _ in range(5):
            store.update_baseline_incremental(
                "carol", None, None,
                extract_linguistic_features("hello there")
            )
        assert store.get_baseline("carol").sample_count == 5

    def test_baseline_reliability(self):
        store = NarrativeStore()
        b = make_baseline(samples=5)
        store.save_baseline(b)
        assert store.get_baseline("alice").is_reliable is False
        b2 = make_baseline(samples=20)
        store.save_baseline(b2)
        assert store.get_baseline("alice").is_reliable is True

    def test_log_anomaly(self):
        store = NarrativeStore()
        store.log_anomaly("alice", 0.85, "voice_stress")
        anomalies = store.get_anomalies("alice")
        assert len(anomalies) == 1
        assert anomalies[0].deception_prob == 0.85

    def test_anomaly_capped_at_100(self):
        store = NarrativeStore()
        for i in range(110):
            store.log_anomaly("alice", 0.5, "micro_exp")
        assert len(store.get_anomalies("alice")) == 100

    def test_register_and_get_contact(self):
        store = NarrativeStore()
        emb = np.random.randn(512).astype(np.float32)
        store.register_contact("dave", "Dave Johnson", emb)
        assert store.get_contact_name("dave") == "Dave Johnson"
        idx = store.get_contact_embeddings()
        assert "dave" in idx
