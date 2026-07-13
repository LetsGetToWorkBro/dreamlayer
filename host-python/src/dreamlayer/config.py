from __future__ import annotations
import os
from dataclasses import dataclass, field


@dataclass
class Paths:
    db:      str = "dreamlayer.db"
    lua_root: str = "../halo-lua"
    hud_out: str = "../assets/hud/samples"


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
    openai_api_key:             str   = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
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


CONFIG = Config()
