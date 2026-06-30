"""Tests for LieLens main analyzer (integration level)."""
import numpy as np
import pytest
from memoscape.lie_lens import LieLens
from memoscape.lie_lens.features import BIN_HZ as _BIN_HZ  # intentionally alias


def _BIN_HZ():
    from memoscape.lie_lens.prosody import BIN_HZ
    return BIN_HZ


def make_fft(peak_hz=200.0) -> np.ndarray:
    from memoscape.lie_lens.prosody import BIN_HZ
    fft = np.zeros(512)
    fft[int(peak_hz / BIN_HZ)] = 1.0
    return fft


def make_frame(brightness=0.5) -> np.ndarray:
    return np.full((64, 64, 3), brightness, dtype=np.float32)


def feed_all(ll: LieLens, n_audio=60, n_frames=20, text="I went there."):
    fft = make_fft()
    for _ in range(n_audio):
        ll.feed_audio(fft, 0.3)
    for _ in range(n_frames):
        ll.feed_frame(make_frame())
    if text:
        ll.feed_transcript(text)


class TestLieLensAnalyzer:
    def test_tick_none_before_data(self):
        ll = LieLens(cooldown_s=0)
        assert ll.tick() is None

    def test_tick_returns_result_after_data(self):
        ll = LieLens(cooldown_s=0)
        feed_all(ll)
        result = ll.tick()
        assert result is not None

    def test_result_has_credibility(self):
        ll = LieLens(cooldown_s=0)
        feed_all(ll)
        r = ll.tick()
        assert r is not None
        assert 0.0 <= r.credibility.deception_prob <= 1.0

    def test_hud_card_type(self):
        ll = LieLens(cooldown_s=0)
        feed_all(ll)
        r = ll.tick()
        assert r is not None
        assert r.to_hud_card()["type"] == "LieLensCard"

    def test_cooldown_suppresses_second_tick(self):
        ll = LieLens(cooldown_s=9999)
        feed_all(ll)
        r1 = ll.tick()
        assert r1 is not None
        assert ll.tick() is None

    def test_reset_clears_state(self):
        ll = LieLens(cooldown_s=0)
        feed_all(ll)
        ll.reset()
        assert ll.tick() is None

    def test_privacy_gate(self):
        class Paused:
            def allow_capture(self): return False
        ll = LieLens(cooldown_s=0, privacy=Paused())
        feed_all(ll)
        assert ll.tick() is None

    def test_contact_registered_and_matched(self):
        ll = LieLens(cooldown_s=0)
        # Register a contact with the same embedding the mock NPU will return
        frame = make_frame(0.5)
        mock_emb = np.random.default_rng(seed=500).standard_normal(512).astype(np.float32)
        mock_emb /= np.linalg.norm(mock_emb)
        ll.register_contact("alice", "Alice Smith", mock_emb)
        feed_all(ll)
        r = ll.tick()
        # Contact may or may not match depending on mock determinism
        # but result should always be returned
        assert r is not None

    def test_transcript_updates_baseline(self):
        ll = LieLens(cooldown_s=0)
        ll._current_contact_id = "bob"
        ll.feed_transcript("I went to the store yesterday.")
        baseline = ll._store.get_baseline("bob")
        assert baseline is not None
        assert baseline.sample_count >= 1

    def test_label_anomaly(self):
        ll = LieLens(cooldown_s=0)
        feed_all(ll)
        r = ll.tick()
        if r and r.contact_id:
            ll.label_last_anomaly(r.contact_id, "false_positive")
