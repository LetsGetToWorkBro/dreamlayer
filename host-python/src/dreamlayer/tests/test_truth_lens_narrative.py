"""Tests for the NarrativeStore.

Rewritten against the shipped schema API (AUFrame / ProsodyFrame /
LinguisticFrame / ContactBaseline) — the previous version targeted a
draft API (ActionUnits / *Features) that never landed, so the module
failed at import and the whole file was dead weight in CI.
"""
from dreamlayer.truth_lens.narrative_store import NarrativeStore
from dreamlayer.truth_lens.schema import AUFrame, ProsodyFrame, LinguisticFrame


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
        complexity_score=0.4, negation_rate=0.1, word_count=50,
    )


def update(ns, contact_id):
    return ns.update_baseline(
        contact_id, au=make_au(), prosody=make_prosody(),
        linguistic=make_linguistic(),
    )


class TestNarrativeStore:
    def test_get_baseline_none_initially(self):
        ns = NarrativeStore()
        assert ns.get_baseline("alice") is None

    def test_update_baseline_creates_entry(self):
        ns = NarrativeStore()
        bl = update(ns, "alice")
        assert bl.contact_id == "alice"
        assert bl.sample_count == 1

    def test_update_baseline_increments_count(self):
        ns = NarrativeStore()
        for _ in range(5):
            update(ns, "alice")
        assert ns.get_baseline("alice").sample_count == 5

    def test_calibrated_after_10_samples(self):
        ns = NarrativeStore()
        for _ in range(10):
            update(ns, "alice")
        assert ns.get_baseline("alice").is_calibrated

    def test_not_calibrated_before_10(self):
        ns = NarrativeStore()
        for _ in range(9):
            update(ns, "alice")
        assert not ns.get_baseline("alice").is_calibrated

    def test_partial_frames_DO_update(self):
        """Whatever channels arrived are learned from — the inverse of what this
        test used to assert.

        It pinned "update_baseline requires all three modalities before it
        commits", which was the bug rather than the contract. `au` is
        permanently None on every surface the Brain has (no camera, and
        `fusion.AU_CHANNEL_REAL` is False in any case), so the all-three rule
        meant no baseline was EVER written on the product: `get_baseline`
        answered None forever, `fuse` took its stranger branch forever, and the
        known-contact path fusion.py advertises was unreachable code.

        Requiring the synthetic AU channel to be present before anything could
        be learned was the contradiction at the heart of it — the same channel
        the codebase had already decided must not influence a verdict.
        """
        ns = NarrativeStore()
        ns.update_baseline("alice", au=make_au(), prosody=None, linguistic=None)
        bl = ns.get_baseline("alice")
        assert bl is not None, "an AU-only observation taught the baseline nothing"
        assert bl.sample_count == 1 and bl.au_n == 1
        assert bl.prosody_n == 0 and bl.linguistic_n == 0

        # The case that actually matters on this product: no camera at all.
        ns.update_baseline("bob", au=None, prosody=make_prosody(),
                           linguistic=make_linguistic())
        bob = ns.get_baseline("bob")
        assert bob is not None, (
            "a Brain with a microphone and no camera could not learn a baseline")
        assert bob.prosody_n == 1 and bob.linguistic_n == 1 and bob.au_n == 0

    def test_an_empty_observation_teaches_nothing(self):
        """The other side of accepting partial frames: no channel at all must
        NOT advance the sample count. `confidence` scales on `sample_count`, so
        a silent conversation would otherwise calibrate a baseline that has
        observed nothing and raise confidence on no evidence."""
        ns = NarrativeStore()
        ns.update_baseline("dave", au=None, prosody=None, linguistic=None)
        assert ns.get_baseline("dave") is None

    def test_prosody_baseline_stored(self):
        ns = NarrativeStore()
        update(ns, "bob")
        bl = ns.get_baseline("bob")
        assert "jitter_pct" in bl.prosody_mean
        assert abs(bl.prosody_mean["jitter_pct"] - 1.0) < 1e-6

    def test_linguistic_baseline_stored(self):
        ns = NarrativeStore()
        update(ns, "bob")
        bl = ns.get_baseline("bob")
        assert "hedging_rate" in bl.linguistic_mean
        assert abs(bl.linguistic_mean["hedging_rate"] - 0.1) < 1e-6

    def test_au_mean_converges(self):
        ns = NarrativeStore()
        for _ in range(10):
            update(ns, "carol")
        bl = ns.get_baseline("carol")
        assert all(abs(m - 0.3) < 1e-6 for m in bl.au_mean)

    def test_log_anomaly_stores_entry(self):
        ns = NarrativeStore()
        ns.log_anomaly("alice", deception_prob=0.8,
                       dominant_channel="voice_stress",
                       user_label="confirmed")
        logs = ns.get_anomaly_log("alice")
        assert len(logs) == 1
        assert logs[0]["user_label"] == "confirmed"
        assert logs[0]["dominant_channel"] == "voice_stress"

    def test_get_anomaly_log_empty_initially(self):
        ns = NarrativeStore()
        assert ns.get_anomaly_log("nobody") == []

    def test_contact_count(self):
        ns = NarrativeStore()
        update(ns, "alice")
        update(ns, "bob")
        assert ns.contact_count() >= 2


class TestForget:
    """Audit 2026-07-14 HIGH: 'forget that' must erase the deception baseline
    AND the anomaly log for a person."""

    def test_forget_erases_baseline_and_log(self):
        ns = NarrativeStore()
        for _ in range(3):
            update(ns, "carol")
        ns.log_anomaly("carol", 0.8, "voice_stress")
        assert ns.get_baseline("carol") is not None
        assert ns.get_anomaly_log("carol")
        ns.forget("carol")
        assert ns.get_baseline("carol") is None
        assert ns.get_anomaly_log("carol") == []
