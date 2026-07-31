"""truth_lens/schema.py — All data structures for the Lie Lens pipeline."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Per-frame sensor payloads
# ---------------------------------------------------------------------------

@dataclass
class AUFrame:
    """17 facial Action Unit activations from one camera frame.

    AU indices follow the Facial Action Coding System (FACS).
    Values are 0.0 (absent) → 1.0 (maximum activation).
    """
    au_values: list[float]          # length 17
    face_confidence: float          # detection confidence 0-1
    embedding: Optional[list[float]] = None  # 512-d face embedding

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
    hesitation_rate: float          # filled pauses per second (um, uh)
    pause_ratio: float              # fraction of window that is silence
    speech_rate_norm: float         # 1.0 = baseline, >1 fast, <1 slow
    energy_db: float

    def stress_score(self) -> float:
        """Heuristic 0-1 stress score for this window."""
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
    hedging_rate: float             # hedge words / total words
    first_person_rate: float        # 1st-person pronouns / total words
    complexity_score: float         # 0=simple, 1=complex (avg sentence length)
    negation_rate: float            # negation words / total words
    word_count: int

    def deception_score(self) -> float:
        """Heuristic 0-1 deception score from linguistic features.

        Each channel contributes fraction-of-saturation × channel weight
        (weights: hedging .30, first-person .25, complexity .25,
        negation .20). The previous form capped the *fraction* at the
        weight instead of scaling it, so calm speech scored ~0.43.
        """
        score = 0.0
        # High hedging = uncertainty / distancing (saturates at 15%)
        score += min(self.hedging_rate / 0.15, 1.0) * 0.30
        # Low first-person = distancing from statements
        first_person_dev = max(0.0, 0.08 - self.first_person_rate)
        score += min(first_person_dev / 0.08, 1.0) * 0.25
        # High complexity = over-qualification
        score += min(self.complexity_score, 1.0) * 0.25
        # High negation = defensive language (saturates at 10%)
        score += min(self.negation_rate / 0.10, 1.0) * 0.20
        return min(score, 1.0)


# ---------------------------------------------------------------------------
# Per-contact memory
# ---------------------------------------------------------------------------

@dataclass
class ContactBaseline:
    """Learned baseline for a known contact (normal, non-stressed state)."""
    contact_id: str
    au_mean: list[float] = field(default_factory=lambda: [0.0] * 17)
    au_std: list[float] = field(default_factory=lambda: [0.1] * 17)
    prosody_mean: dict = field(default_factory=dict)
    prosody_std: dict = field(default_factory=dict)
    linguistic_mean: dict = field(default_factory=dict)
    linguistic_std: dict = field(default_factory=dict)
    sample_count: int = 0
    is_calibrated: bool = False     # True after MIN_CALIBRATION_SAMPLES
    # PER-CHANNEL sample counts. `sample_count` counts observations that carried
    # at least one channel; these count the observations that carried THIS one.
    # Welford's running mean divides the delta by the number of samples that
    # actually contributed, so a channel present on only some observations must
    # not be divided by the global count — doing so weights each new reading far
    # too lightly and the mean crawls toward the truth instead of converging on
    # it. Default 0 so a baseline persisted before these existed still loads.
    au_n: int = 0
    prosody_n: int = 0
    linguistic_n: int = 0
    # Welford's running sum of squared deviations from the running mean, per
    # feature. Without it there is no way to compute a real standard deviation
    # online, and its absence is what made `*_std` meaningless — see `update`.
    au_m2: list[float] = field(default_factory=lambda: [0.0] * 17)
    prosody_m2: dict = field(default_factory=dict)
    linguistic_m2: dict = field(default_factory=dict)

    MIN_CALIBRATION_SAMPLES: int = field(default=10, init=False, repr=False)

    def update(self, au: Optional[AUFrame], prosody: Optional[ProsodyFrame],
               linguistic: Optional[LinguisticFrame]) -> None:
        """Incremental mean/std update (Welford's online algorithm).

        Every channel is OPTIONAL, and that is the whole point of this signature.

        It used to require all three, and `NarrativeStore.update_baseline`
        enforced it with `if au is not None and prosody is not None and
        linguistic is not None`. On any surface without a camera — which is every
        surface the Brain has — `au` is permanently None, so the baseline never
        updated, `get_baseline` kept returning None, and `FusionEngine.fuse` took
        its conservative stranger branch forever. The stranger branch dampens its
        output to `max(score) * 0.3`, i.e. at most 0.30 against a 0.30 display
        threshold, so the per-contact personalisation this module advertises
        ("Known contact: z-scores vs personal baseline → higher accuracy") could
        never engage and the Truth Lens could never draw a single card.

        Requiring AU was doubly wrong, because `fusion.AU_CHANNEL_REAL` is False:
        the codebase had already concluded the AU channel is synthetic and must
        not influence a verdict, and then made learning anything conditional on
        that same synthetic channel being present. Fusion itself has always
        treated the channels independently (`if prosody is not None: ... else:
        0.0`); this now matches.

        A call with no channel at all is a no-op — it must not advance
        `sample_count`, or a silent conversation would "calibrate" a baseline
        that has observed nothing and `confidence` (which scales on
        `sample_count`) would rise on no evidence.
        """
        if au is None and prosody is None and linguistic is None:
            return
        self.sample_count += 1

        def upd(mean: dict, std: dict, m2: dict, name: str, v: float, n: int) -> None:
            """One Welford step for one feature.

            `m2` accumulates the sum of squared deviations, which is the whole
            reason this is Welford's algorithm rather than a running mean with a
            std-shaped expression next to it. What used to sit here was

                std[name] = max(0.01, abs(delta * (v - m)) ** 0.5)

            — the square root of THIS sample's contribution to the variance, kept
            in place of the variance itself. It never accumulated, so it did not
            converge on anything: over fourteen readings of a speaker whose true
            spread was 2.02 Hz it stored, in order, 0.98, 2.70, 2.10, 1.69, 0.14,
            2.16, 1.49, 2.23, 1.01, 1.86, 1.54, 1.15, 4.17. A thirty-fold swing,
            driven entirely by which utterance happened to be most recent.

            Every z-score in `fusion._avg_abs_z` divides by that number, so the
            "personal baseline" — the accuracy the known-contact path exists to
            deliver — multiplied the evidence by a random factor. The same
            utterance from the same person could read as half a sigma or fifteen,
            and `_known_fuse` turns z into a score via `min(z / 4.0, 1.0)`, so
            fifteen saturates the channel outright. That is worse than the
            stranger heuristic it was supposed to improve on: it does not merely
            fail to personalise, it injects noise while claiming precision.
            """
            m = mean.get(name, 0.0)
            delta = v - m
            m += delta / n
            mean[name] = m
            m2[name] = m2.get(name, 0.0) + delta * (v - m)
            # Sample standard deviation (n-1). The 0.01 floor keeps a genuinely
            # constant feature from dividing by zero; with a real running
            # variance it is now a guard rather than, as before, the value the
            # estimate kept collapsing to.
            std[name] = (max(0.01, (m2[name] / (n - 1)) ** 0.5) if n > 1
                         else 0.1)

        if au is not None:
            self.au_n += 1
            n = self.au_n
            for i, v in enumerate(au.au_values):
                delta = v - self.au_mean[i]
                self.au_mean[i] += delta / n
                self.au_m2[i] += delta * (v - self.au_mean[i])
                self.au_std[i] = (max(0.01, (self.au_m2[i] / (n - 1)) ** 0.5)
                                  if n > 1 else 0.1)

        if prosody is not None:
            self.prosody_n += 1
            for name in ("pitch_mean_hz", "pitch_variance", "jitter_pct",
                         "shimmer_pct", "hesitation_rate", "pause_ratio",
                         "speech_rate_norm", "energy_db"):
                upd(self.prosody_mean, self.prosody_std, self.prosody_m2, name,
                    getattr(prosody, name), self.prosody_n)

        if linguistic is not None:
            self.linguistic_n += 1
            for name in ("hedging_rate", "first_person_rate",
                         "complexity_score", "negation_rate"):
                upd(self.linguistic_mean, self.linguistic_std,
                    self.linguistic_m2, name,
                    getattr(linguistic, name), self.linguistic_n)

        # Mark calibrated
        self.is_calibrated = self.sample_count >= self.MIN_CALIBRATION_SAMPLES


# ---------------------------------------------------------------------------
# Fusion output
# ---------------------------------------------------------------------------

@dataclass
class CredibilityVector:
    """Multi-dimensional deception likelihood output from the fusion engine."""
    deception_prob: float           # 0.0 (credible) → 1.0 (deceptive)
    confidence: float               # 0.0 (no data) → 1.0 (fully calibrated)
    micro_expression_z: float       # z-score vs baseline
    voice_stress_z: float           # z-score vs baseline
    linguistic_z: float             # z-score vs baseline
    dominant_channel: str           # which channel is driving the score
    is_stranger: bool = False       # True if no baseline available

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
        """Halo RGB565 color for HUD overlay."""
        if self.confidence < 0.3:
            return 0x7BEF   # grey
        if self.deception_prob < 0.40:
            return 0x07E0   # green
        if self.deception_prob < 0.65:
            return 0xFFE0   # yellow
        if self.deception_prob < 0.85:
            return 0xFD20   # orange
        return 0xF800       # red


# ---------------------------------------------------------------------------
# Top-level result
# ---------------------------------------------------------------------------

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
        """Render as a Halo HUD card dict."""
        c = self.credibility
        name_line = self.contact_name or ("Stranger" if c.is_stranger else "Unknown")
        return {
            "type": "TruthLensCard",
            "dismiss_ms": 5000,
            "label": c.label,
            "deception_prob": round(c.deception_prob, 2),
            "confidence": round(c.confidence, 2),
            "color": c.hud_color,
            "eyebrow": "LIE LENS",
            "primary": c.label,
            "detail": f"{c.dominant_channel}  •  {round(c.deception_prob * 100)}%",
            "footer": name_line,
            "opacity": 0.9 if c.confidence >= 0.3 else 0.4,
            "is_stranger": c.is_stranger,
            "lines": ["LIE LENS", c.label,
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

    # ------------------------------------------------------------------
    # Halo Cinema v1: 9-ring gauge card (docs/HALO_CINEMA_V1.md Phase 4)
    # ------------------------------------------------------------------

    # Ordered gauge stages: 7 analysis rings + aggregate + verdict
    GAUGE_STAGES = (
        "face", "au", "voice", "prosody", "linguistic",
        "narrative", "fusion", "aggregate", "verdict",
    )

    def gauge_stages(self) -> list[dict]:
        """Per-stage {name, confidence, direction} for the 9-ring gauge.

        direction: "truthful" | "deceptive" | "insufficient" — a stage with
        no data reads insufficient (slate ring), matching the design rule
        that absence of evidence is displayed, never hidden.
        """
        c = self.credibility

        def z_stage(name: str, z: float, present: bool) -> dict:
            if not present:
                return {"name": name, "confidence": 0.0, "direction": "insufficient"}
            strength = min(abs(z) / 3.0, 1.0)
            direction = "deceptive" if z > 1.0 else "truthful"
            return {"name": name, "confidence": round(max(strength, 0.15), 3),
                    "direction": direction}

        has_face  = self.au_frame is not None
        has_voice = self.prosody_frame is not None
        has_ling  = self.linguistic_frame is not None

        face_conf = self.au_frame.face_confidence if self.au_frame is not None else 0.0
        stages = [
            {"name": "face", "confidence": round(face_conf, 3),
             "direction": "truthful" if has_face else "insufficient"},
            z_stage("au", c.micro_expression_z, has_face),
            {"name": "voice",
             "confidence": round(self.prosody_frame.stress_score(), 3) if self.prosody_frame is not None else 0.0,
             "direction": ("deceptive" if has_voice and c.voice_stress_z > 1.0
                           else "truthful" if has_voice else "insufficient")},
            z_stage("prosody", c.voice_stress_z, has_voice),
            z_stage("linguistic", c.linguistic_z, has_ling),
            {"name": "narrative", "confidence": 0.0, "direction": "insufficient"},
            {"name": "fusion", "confidence": round(c.confidence, 3),
             "direction": "deceptive" if c.deception_prob >= 0.5 else "truthful"},
            {"name": "aggregate", "confidence": round(c.confidence, 3),
             "direction": "deceptive" if c.deception_prob >= 0.5 else "truthful"},
            {"name": "verdict", "confidence": round(c.deception_prob, 3),
             "direction": "deceptive" if c.deception_prob >= 0.5 else "truthful"},
        ]
        return stages

    def to_gauge_card(self, origin: Optional[dict] = None) -> dict:
        """Render as a TruthLensCard 9-ring gauge payload.

        origin: {"x", "y"} eye-landmark display coords for the Truth Ripple
        entry signature; defaults to the upper face zone (128, 96).
        """
        c = self.credibility
        # ONE builder for one card type. This used to assemble the dict inline,
        # which made it a second, independent definition of the TruthLensCard
        # payload alongside `hud/cards.py:truth_gauge_card` — and the two had
        # already drifted (different rounding, an `is_stranger` key on one side
        # only). It also meant the HUD reachability checker, which maps a card
        # type to the builder that makes it, could not see this path as a
        # producer at all: "Read the room" read as having no Brain-side producer
        # while a Brain-side producer was pushing it.
        #
        # Imported here rather than at module scope so `truth_lens.schema` stays
        # importable without pulling the HUD theme stack in behind it.
        from ..hud.cards import truth_gauge_card
        card = truth_gauge_card(
            verdict=c.label,
            stages=self.gauge_stages(),
            confidence=round(c.confidence, 2),
            deception_prob=c.deception_prob,
            origin=origin,
            footer=self.contact_name or ("Stranger" if c.is_stranger else "Unknown"),
        )
        # The two fields this richer caller adds on top of the plain builder: it
        # knows whether the read had a personal baseline behind it, and it can
        # put the number into words for a surface that draws `lines` rather than
        # the gauge.
        card["deception_prob"] = round(c.deception_prob, 2)
        card["is_stranger"] = c.is_stranger
        card["lines"] = ["TRUTH LENS", c.label,
                         f"{round(c.deception_prob * 100)}% deception signal"]
        return card
