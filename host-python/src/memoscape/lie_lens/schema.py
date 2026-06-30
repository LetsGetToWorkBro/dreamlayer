"""lie_lens/schema.py — All dataclasses for Lie Lens."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Per-frame signal snapshots
# ---------------------------------------------------------------------------

@dataclass
class AUFrame:
    """One frame of facial action unit data (17 AUs, 0-1 activation each)."""
    aus: list[float]          # 17-element list, AU indices match FACS standard
    micro_exp_label: str      # e.g. 'contempt', 'fear', 'neutral'
    micro_exp_confidence: float

    # FACS AUs most associated with deception cues
    DECEPTION_AUS = {6, 7, 10, 12, 14, 17, 20, 24}  # AU indices (1-based)

    def deception_au_score(self) -> float:
        """Mean activation of deception-relevant AUs (0-1)."""
        if not self.aus:
            return 0.0
        relevant = [self.aus[i - 1] for i in self.DECEPTION_AUS
                    if i - 1 < len(self.aus)]
        return sum(relevant) / len(relevant) if relevant else 0.0


@dataclass
class ProsodyFrame:
    """Voice prosody features from one 200ms audio window."""
    pitch_mean_hz: float
    pitch_variance: float
    jitter_pct: float
    shimmer_pct: float
    hesitation_rate: float    # pauses-per-second
    energy_db: float
    speech_rate_norm: float   # 1.0 = baseline

    def stress_score(self) -> float:
        """0-1 heuristic stress score for this window."""
        s = 0.0
        s += min(self.pitch_variance / 500.0, 0.25)
        s += min(self.jitter_pct / 5.0, 0.20)
        s += min(self.shimmer_pct / 8.0, 0.20)
        s += min(self.hesitation_rate / 4.0, 0.20)
        s += min(abs(self.speech_rate_norm - 1.0) / 0.5, 0.15)
        return min(s, 1.0)


@dataclass
class LinguisticFrame:
    """Linguistic deception markers from one utterance."""
    text: str
    hedging_score: float      # 0-1: "maybe", "kind of", "I think" density
    first_person_rate: float  # fraction of words that are I/me/my
    complexity_score: float   # sentence complexity (lower = distancing)
    negation_rate: float      # frequency of negations
    specificity_score: float  # 0-1: high = very specific details

    def deception_score(self) -> float:
        """0-1 heuristic deception score from linguistic features."""
        s = 0.0
        s += self.hedging_score * 0.30
        # Low first-person use is a known deception marker
        s += (1.0 - min(self.first_person_rate / 0.15, 1.0)) * 0.25
        s += (1.0 - self.complexity_score) * 0.20
        s += self.negation_rate * 0.15
        s += (1.0 - self.specificity_score) * 0.10
        return min(s, 1.0)


# ---------------------------------------------------------------------------
# Fusion output
# ---------------------------------------------------------------------------

@dataclass
class CredibilityVector:
    """Output of the fusion engine — multi-dimensional credibility assessment."""
    deception_prob: float       # 0-1 overall deception probability
    confidence: float           # 0-1 confidence in the estimate
    micro_exp_z: float          # z-score vs contact baseline
    voice_stress_z: float
    linguistic_z: float
    dominant_signal: str        # which dimension is driving the score
    is_stranger: bool           # True = no baseline, conservative mode
    window_count: int

    # Thresholds
    DECEPTION_THRESHOLD = 0.72
    CONFIDENCE_THRESHOLD = 0.60
    STRANGER_DECEPTION_THRESHOLD = 0.92  # much higher for strangers

    @property
    def should_alert(self) -> bool:
        threshold = (self.STRANGER_DECEPTION_THRESHOLD if self.is_stranger
                     else self.DECEPTION_THRESHOLD)
        return (self.deception_prob >= threshold
                and self.confidence >= self.CONFIDENCE_THRESHOLD)

    @property
    def label(self) -> str:
        if self.confidence < 0.3:
            return "READING"
        if self.is_stranger and self.deception_prob < self.STRANGER_DECEPTION_THRESHOLD:
            return "STRANGER"
        if self.deception_prob < 0.35:
            return "CREDIBLE"
        if self.deception_prob < 0.55:
            return "UNCERTAIN"
        if self.deception_prob < 0.72:
            return "ELEVATED"
        if self.deception_prob < 0.90:
            return "DECEPTIVE"
        return "HIGH DECEPTION"

    @property
    def hud_color(self) -> int:
        """Halo RGB565 color."""
        if self.confidence < 0.3:
            return 0x7BEF   # grey
        if self.deception_prob < 0.35:
            return 0x07E0   # green
        if self.deception_prob < 0.55:
            return 0xFFE0   # yellow
        if self.deception_prob < 0.72:
            return 0xFD20   # orange
        return 0xF800       # red


# ---------------------------------------------------------------------------
# Per-contact memory
# ---------------------------------------------------------------------------

@dataclass
class ContactBaseline:
    """Stored baseline for one known contact."""
    contact_id: str
    au_mean: list[float]          # mean AU activations (17 values)
    au_std: list[float]           # std dev per AU
    prosody_pitch_mean: float
    prosody_pitch_std: float
    prosody_jitter_mean: float
    prosody_shimmer_mean: float
    linguistic_hedge_mean: float
    linguistic_fp_mean: float     # first-person rate mean
    sample_count: int             # frames used to build baseline

    MIN_SAMPLES = 20              # minimum before baseline is trusted

    @property
    def is_reliable(self) -> bool:
        return self.sample_count >= self.MIN_SAMPLES


@dataclass
class AnomalyRecord:
    """One logged anomaly event for a contact."""
    contact_id: str
    timestamp: float
    deception_prob: float
    dominant_signal: str
    user_label: Optional[str] = None   # 'confirmed', 'false_positive', None


# ---------------------------------------------------------------------------
# Final output
# ---------------------------------------------------------------------------

@dataclass
class LieLensResult:
    """Output emitted by LieLens.tick() when a displayable result is ready."""
    credibility: CredibilityVector
    contact_id: Optional[str] = None
    contact_name: Optional[str] = None
    au_frame: Optional[AUFrame] = None
    prosody_frame: Optional[ProsodyFrame] = None
    linguistic_frame: Optional[LinguisticFrame] = None

    def to_hud_card(self) -> dict:
        c = self.credibility
        name_line = self.contact_name or ("Stranger" if c.is_stranger else "Unknown")
        return {
            "type": "LieLensCard",
            "dismiss_ms": 5000,
            "label": c.label,
            "deception_prob": round(c.deception_prob, 2),
            "confidence": round(c.confidence, 2),
            "dominant_signal": c.dominant_signal,
            "color": c.hud_color,
            "should_alert": c.should_alert,
            "is_stranger": c.is_stranger,
            "eyebrow": "LIE LENS",
            "primary": c.label,
            "name": name_line,
            "detail": f"{c.dominant_signal}  •  {round(c.deception_prob * 100)}%",
            "footer": f"{c.window_count} windows  •  conf {round(c.confidence * 100)}%",
            "opacity": 0.9 if c.confidence >= 0.6 else 0.5,
            "lines": ["LIE LENS", name_line, c.label,
                      f"{round(c.deception_prob * 100)}% deception prob"],
            "layout": {
                "eyebrow": {"x": 128, "y": 196, "size": "sm",
                            "color": c.hud_color, "tracking": 3},
                "primary": {"x": 128, "y": 214, "size": "sm", "color": c.hud_color},
                "name":    {"x": 128, "y": 230, "size": "sm", "color": 0xFFFF},
                "detail":  {"x": 128, "y": 246, "size": "sm", "color": 0x5EF7},
            },
            "chromatic_aberration": c.voice_stress_z * 0.008 if c.should_alert else 0,
            "particle_color": 0xF800 if c.deception_prob > 0.90 else 0x07E0,
        }
