"""truth_lens/schema.py — All data structures for the Truth Lens pipeline."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AUFrame:
    """17 facial Action Unit activations from one camera frame."""
    au_values: list[float]
    face_confidence: float
    embedding: Optional[list[float]] = None

    def __post_init__(self):
        if len(self.au_values) != 17:
            raise ValueError(f"au_values must have 17 elements, got {len(self.au_values)}")


@dataclass
class ProsodyFrame:
    """Acoustic stress features extracted from one audio window."""
    pitch_mean_hz: float
    pitch_variance: float
    jitter_pct: float
    shimmer_pct: float
    hesitation_rate: float
    pause_ratio: float
    speech_rate_norm: float
    energy_db: float

    def stress_score(self) -> float:
        score = 0.0
        score += min(self.pitch_variance / 500.0, 0.20)
        score += min(self.jitter_pct / 5.0, 0.20)
        score += min(self.shimmer_pct / 8.0, 0.20)
        score += min(self.hesitation_rate / 3.0, 0.20)
        score += min(abs(self.pause_ratio - 0.25) / 0.25, 0.10)
        score += min(abs(self.speech_rate_norm - 1.0) / 0.5, 0.10)
        return min(score, 1.0)


@dataclass
class LinguisticFrame:
    """Linguistic deception markers from one utterance."""
    hedging_rate: float
    first_person_rate: float
    complexity_score: float
    negation_rate: float
    word_count: int

    def deception_score(self) -> float:
        score = 0.0
        score += min(self.hedging_rate / 0.15, 0.30)
        first_person_dev = max(0.0, 0.08 - self.first_person_rate)
        score += min(first_person_dev / 0.08, 0.25)
        score += min(self.complexity_score, 0.25) * 0.8
        score += min(self.negation_rate / 0.10, 0.20)
        return min(score, 1.0)


@dataclass
class ContactBaseline:
    """Learned baseline for a known contact."""
    contact_id: str
    au_mean: list[float] = field(default_factory=lambda: [0.0] * 17)
    au_std: list[float] = field(default_factory=lambda: [0.1] * 17)
    prosody_mean: dict = field(default_factory=dict)
    prosody_std: dict = field(default_factory=dict)
    linguistic_mean: dict = field(default_factory=dict)
    linguistic_std: dict = field(default_factory=dict)
    sample_count: int = 0
    is_calibrated: bool = False

    MIN_CALIBRATION_SAMPLES: int = field(default=10, init=False, repr=False)

    def update(self, au: AUFrame, prosody: ProsodyFrame,
               linguistic: LinguisticFrame) -> None:
        self.sample_count += 1
        n = self.sample_count
        for i, v in enumerate(au.au_values):
            delta = v - self.au_mean[i]
            self.au_mean[i] += delta / n
            delta2 = v - self.au_mean[i]
            self.au_std[i] = max(0.01, abs(delta * delta2) ** 0.5 if n > 1 else 0.1)
        self.is_calibrated = n >= self.MIN_CALIBRATION_SAMPLES


@dataclass
class CredibilityVector:
    """Multi-dimensional deception likelihood output."""
    deception_prob: float
    confidence: float
    micro_expression_z: float
    voice_stress_z: float
    linguistic_z: float
    dominant_channel: str
    is_stranger: bool = False

    @property
    def label(self) -> str:
        if self.confidence < 0.3:
            return "CALIBRATING"
        if self.deception_prob < 0.40:
            return "CREDIBLE"
        if self.deception_prob < 0.65:
            return "UNCERTAIN"
        if self.deception_prob < 0.85:
            return "ELEVATED"
        return "HIGH ALERT"

    @property
    def hud_color(self) -> int:
        if self.confidence < 0.3:
            return 0x7BEF
        if self.deception_prob < 0.40:
            return 0x07E0
        if self.deception_prob < 0.65:
            return 0xFFE0
        if self.deception_prob < 0.85:
            return 0xFD20
        return 0xF800


@dataclass
class TruthLensResult:
    """Complete output from one TruthLens analysis cycle."""
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
            "type": "TruthLensCard",
            "dismiss_ms": 5000,
            "label": c.label,
            "deception_prob": round(c.deception_prob, 2),
            "confidence": round(c.confidence, 2),
            "color": c.hud_color,
            "eyebrow": "TRUTH LENS",
            "primary": c.label,
            "detail": f"{c.dominant_channel}  •  {round(c.deception_prob * 100)}%",
            "footer": name_line,
            "opacity": 0.9 if c.confidence >= 0.3 else 0.4,
            "is_stranger": c.is_stranger,
            "lines": ["TRUTH LENS", c.label,
                      f"{round(c.deception_prob * 100)}% deception signal"],
            "layout": {
                "eyebrow": {"x": 128, "y": 196, "size": "sm",
                            "color": c.hud_color, "tracking": 3},
                "primary": {"x": 128, "y": 214, "size": "sm",
                            "color": c.hud_color},
                "detail":  {"x": 128, "y": 230, "size": "sm",
                            "color": 0x5EF7},
                "footer":  {"x": 128, "y": 246, "size": "sm",
                            "color": 0x39E7},
            },
            "renderer_hints": {
                "chromatic_aberration": c.voice_stress_z > 2.0,
                "particle_color": c.hud_color,
                "bone_conduction_delay_ms": (
                    int(c.linguistic_z * 5) if c.linguistic_z > 1.5 else 0
                ),
            },
        }
