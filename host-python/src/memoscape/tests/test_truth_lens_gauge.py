"""Tests for the Truth Lens 9-ring gauge card (Halo Cinema v1, Phase 4)."""
import pytest

from memoscape.lie_lens.renderer import LieLensRenderer
from memoscape.lie_lens.schema import (
    AUFrame, CredibilityVector, LieLensResult, LinguisticFrame, ProsodyFrame,
)


def make_result(deception=0.7, confidence=0.8, au_z=2.0, voice_z=0.5,
                ling_z=0.3, with_frames=True, stranger=False):
    cv = CredibilityVector(
        deception_prob=deception, confidence=confidence,
        micro_expression_z=au_z, voice_stress_z=voice_z,
        linguistic_z=ling_z, dominant_channel="micro_expression",
        is_stranger=stranger,
    )
    au = AUFrame(au_values=[0.4] * 17, face_confidence=0.92) if with_frames else None
    pros = ProsodyFrame(
        pitch_mean_hz=180.0, pitch_variance=50.0, jitter_pct=1.0,
        shimmer_pct=1.5, hesitation_rate=0.5, pause_ratio=0.25,
        speech_rate_norm=1.0, energy_db=-20.0,
    ) if with_frames else None
    ling = LinguisticFrame(
        hedging_rate=0.05, first_person_rate=0.08,
        complexity_score=0.3, negation_rate=0.03, word_count=40,
    ) if with_frames else None
    return LieLensResult(credibility=cv, contact_name="Jordan",
                         au_frame=au, prosody_frame=pros, linguistic_frame=ling)


# ---------------------------------------------------------------------------
# gauge_stages()
# ---------------------------------------------------------------------------

def test_gauge_has_exactly_nine_stages():
    stages = make_result().gauge_stages()
    assert len(stages) == 9
    assert [s["name"] for s in stages] == list(LieLensResult.GAUGE_STAGES)


def test_stage_confidences_are_normalized():
    for s in make_result().gauge_stages():
        assert 0.0 <= s["confidence"] <= 1.0


def test_stage_directions_valid():
    for s in make_result().gauge_stages():
        assert s["direction"] in ("truthful", "deceptive", "insufficient")


def test_high_au_z_reads_deceptive():
    stages = make_result(au_z=2.5).gauge_stages()
    au = next(s for s in stages if s["name"] == "au")
    assert au["direction"] == "deceptive"


def test_low_z_reads_truthful():
    stages = make_result(au_z=0.2).gauge_stages()
    au = next(s for s in stages if s["name"] == "au")
    assert au["direction"] == "truthful"


def test_missing_modalities_read_insufficient():
    stages = make_result(with_frames=False).gauge_stages()
    for name in ("face", "au", "voice", "prosody", "linguistic"):
        s = next(x for x in stages if x["name"] == name)
        assert s["direction"] == "insufficient"
        assert s["confidence"] == 0.0


def test_verdict_ring_tracks_deception_prob():
    stages = make_result(deception=0.71).gauge_stages()
    verdict = stages[-1]
    assert verdict["name"] == "verdict"
    assert abs(verdict["confidence"] - 0.71) < 1e-6
    assert verdict["direction"] == "deceptive"


# ---------------------------------------------------------------------------
# to_gauge_card()
# ---------------------------------------------------------------------------

def test_gauge_card_shape():
    card = make_result().to_gauge_card()
    assert card["type"] == "TruthLensCard"
    assert len(card["stages"]) == 9
    assert card["origin"] == {"x": 128, "y": 96}
    assert card["footer"] == "Jordan"


def test_gauge_card_custom_origin():
    card = make_result().to_gauge_card(origin={"x": 100, "y": 80})
    assert card["origin"] == {"x": 100, "y": 80}


# ---------------------------------------------------------------------------
# LieLensRenderer routing + suppression
# ---------------------------------------------------------------------------

def test_renderer_emits_gauge_card():
    card = LieLensRenderer().render(make_result())
    assert card is not None
    assert card["type"] == "TruthLensCard"
    assert "renderer_hints" in card


def test_renderer_suppresses_low_deception():
    assert LieLensRenderer().render(make_result(deception=0.1)) is None


def test_renderer_suppresses_low_confidence():
    assert LieLensRenderer().render(
        make_result(confidence=0.1, stranger=False)) is None


def test_renderer_none_passthrough():
    assert LieLensRenderer().render(None) is None


# ---------------------------------------------------------------------------
# Pillow renderer draws the gauge
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["truth_gauge"])
def test_hud_renderer_draws_gauge(key):
    pytest.importorskip("PIL")
    from memoscape.hud.cards import ALL_SAMPLES
    from memoscape.hud.renderer import CardRenderer
    img = CardRenderer().render(ALL_SAMPLES[key])
    assert img.size == (256, 256)
    # the gauge must actually paint colored pixels (not a blank disc)
    colors = img.convert("RGB").getcolors(maxcolors=100000)
    assert len(colors) > 10
