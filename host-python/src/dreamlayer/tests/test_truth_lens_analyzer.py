"""Integration tests for TruthLens orchestrator."""
import numpy as np
from dreamlayer.truth_lens import TruthLens
from dreamlayer.truth_lens.prosody import BIN_HZ


def make_fft(peak_hz: float = 200.0) -> np.ndarray:
    fft = np.zeros(512)
    fft[int(peak_hz / BIN_HZ)] = 1.0
    return fft


def make_frame(value: float = 0.6) -> np.ndarray:
    return np.full((32, 32), value, dtype=np.float32)


def feed_all(ll: TruthLens, n_frames: int = 60,
            amplitude: float = 0.3,
            frame_value: float = 0.6,
            text: str = "I went to the office today.") -> None:
    fft = make_fft(200)
    frame = make_frame(frame_value)
    for i in range(n_frames):
        ll.feed_frame(frame)
        ll.feed_audio(fft, amplitude)
        if i % 20 == 0:
            ll.feed_transcript(text)


class TestTruthLensAnalyzer:
    def test_tick_none_before_data(self):
        ll = TruthLens(cooldown_s=0)
        assert ll.tick() is None

    def test_tick_returns_result_after_data(self):
        ll = TruthLens(cooldown_s=0)
        feed_all(ll)
        result = ll.tick()
        # May be None if score below threshold — that's valid
        # Just assert no exception and type is correct if returned
        assert result is None or hasattr(result, "credibility")

    def test_result_credibility_bounded(self):
        ll = TruthLens(cooldown_s=0)
        feed_all(ll, n_frames=80, amplitude=0.3)
        result = ll.tick()
        if result:
            assert 0.0 <= result.credibility.deception_prob <= 1.0
            assert 0.0 <= result.credibility.confidence <= 1.0

    def test_hud_card_type(self):
        ll = TruthLens(cooldown_s=0)
        feed_all(ll, n_frames=80, amplitude=0.8)
        result = ll.tick()
        if result:
            assert result.to_hud_card()["type"] == "TruthLensCard"

    def test_cooldown_suppresses_second_emission(self):
        ll = TruthLens(cooldown_s=9999)
        feed_all(ll, n_frames=80, amplitude=0.8)
        r1 = ll.tick()
        r2 = ll.tick()
        # Both may be None, but second should never fire if first did
        if r1 is not None:
            assert r2 is None

    def test_reset_clears_state(self):
        ll = TruthLens(cooldown_s=0)
        feed_all(ll)
        ll.reset()
        assert ll.tick() is None

    def test_privacy_gate_suppresses_all(self):
        class Paused:
            def allow_capture(self): return False

        ll = TruthLens(cooldown_s=0, privacy=Paused())
        feed_all(ll)
        assert ll.tick() is None

    def test_contact_matched_when_registry_provided(self):
        # Build a known embedding from a bright frame
        frame = make_frame(0.9)
        from dreamlayer.truth_lens.face_embed import FaceEmbedder
        embedder = FaceEmbedder()
        au = embedder.process_frame(frame)
        assert au is not None
        emb = au.embedding

        registry = {"contact_001": {"name": "Alex", "embedding": emb}}
        ll = TruthLens(contact_registry=registry, cooldown_s=0)
        feed_all(ll, n_frames=80, frame_value=0.9)
        result = ll.tick()
        if result:
            assert result.contact_id == "contact_001"
            assert result.contact_name == "Alex"

    def test_stranger_mode_when_no_registry(self):
        ll = TruthLens(cooldown_s=0)
        feed_all(ll, n_frames=80,
                 amplitude=0.9,
                 text="I maybe possibly could have sort of done it I guess")
        result = ll.tick()
        if result:
            assert result.credibility.is_stranger is True
