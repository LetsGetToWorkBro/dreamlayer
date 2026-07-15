from __future__ import annotations
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger("dreamlayer.config")


@dataclass
class Paths:
    db:      str = "dreamlayer.db"
    lua_root: str = "../halo-lua"
    hud_out: str = "../assets/hud/samples"


def _env_float(env, name: str):
    """Parse an env var as a float, or None if unset/blank/unparseable. A bad
    value is ignored (logged, default kept) rather than crashing config load —
    a mistyped OPENAI_CONFIDENCE must not take the whole engine down."""
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        log.warning("config: ignoring %s=%r (not a number)", name, raw)
        return None


@dataclass
class Config:
    paths:                      Paths = field(default_factory=Paths)
    capture_min_interval_ms:    int   = 4000
    proactive_min_confidence:   float = 0.45
    # Recall acceptance floor on the blended (similarity+confidence) score. Set
    # for the real lexical embedder (HashingEmbeddingProvider), whose partial-
    # match cosines are lower-magnitude — and better calibrated — than the old
    # 32-d mock's, so the floor tracks it rather than the fixture.
    recall_min_confidence:      float = 0.35
    reduce_motion:              bool  = False

    # LLM tier-3 extraction
    llm_model:                  str   = "gpt-4o-mini"
    llm_confidence_threshold:   float = 0.60
    llm_word_threshold:         int   = 40
    llm_timeout_s:              float = 4.0
    # repr=False so the key never lands in a repr(CONFIG) / asdict / traceback
    # dump (audit 2026-07-14 — it was a latent secret-in-logs surface).
    openai_api_key:             str   = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""),
        repr=False,
    )

    # Passive recall primitives
    passive_ring_capacity:      int   = 64
    passive_min_confidence:     float = 0.55
    # enforced by PassiveEventInjector itself (P2-15): however often the host
    # calls Orchestrator.tick(), the ring is scanned at most once per interval
    passive_tick_interval_ms:   int   = 250

    # Retention lifecycle (memory/retention.py): hot ring → warm store →
    # cold entities. REM promotion is the only road from hot to lasting.
    retention_hot_hours:        float = 24.0
    retention_warm_days:        float = 90.0

    def __post_init__(self) -> None:
        # Lightweight bounds so an out-of-range value can't silently disable a
        # privacy-relevant gate (e.g. a >1.0 confidence floor that never rejects)
        # — clamp rather than raise, since CONFIG is a mutable runtime singleton
        # (audit 2026-07-14).
        for name in ("proactive_min_confidence", "recall_min_confidence",
                     "passive_min_confidence", "llm_confidence_threshold"):
            v = getattr(self, name)
            setattr(self, name, min(1.0, max(0.0, float(v))))
        for name in ("capture_min_interval_ms", "passive_tick_interval_ms",
                     "passive_ring_capacity", "llm_word_threshold"):
            setattr(self, name, max(0, int(getattr(self, name))))
        # A zero/negative network timeout is a silent footgun (urllib blocks or
        # fails instantly), and negative retention windows would make the
        # lifecycle nonsensical — floor them too (audit 2026-07-14 flagged only
        # the confidences; these fields could still fail silently).
        self.llm_timeout_s = max(0.1, float(self.llm_timeout_s))
        self.retention_hot_hours = max(0.0, float(self.retention_hot_hours))
        self.retention_warm_days = max(0.0, float(self.retention_warm_days))

    @classmethod
    def from_env(cls, env=None) -> "Config":
        """Build a Config honoring environment overrides.

        Precedence is explicit and one-way: an environment variable, when set to
        a parseable value, wins over the dataclass default; anything unset or
        unparseable falls back to the default (never raises, never half-applies).
        This is the *single* place the environment is read for tuning knobs, so
        `.env.example` can document exactly these names — the file had drifted to
        knobs no code read (audit 2026-07-14). Env-overridable fields:

            OPENAI_API_KEY      -> openai_api_key
            OPENAI_MODEL        -> llm_model
            OPENAI_CONFIDENCE   -> llm_confidence_threshold
        """
        env = os.environ if env is None else env
        over: dict = {"openai_api_key": env.get("OPENAI_API_KEY", "")}
        model = env.get("OPENAI_MODEL")
        if model:
            over["llm_model"] = model
        conf = _env_float(env, "OPENAI_CONFIDENCE")
        if conf is not None:
            over["llm_confidence_threshold"] = conf
        return cls(**over)


CONFIG = Config.from_env()
