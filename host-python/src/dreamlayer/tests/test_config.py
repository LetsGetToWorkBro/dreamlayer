"""test_config.py — the tuning-knob module: defaults, the repr-redacted secret,
range/timeout validation, and a single clear env precedence (env > default).

Audit 2026-07-14 flagged config.py C+ for a repr-exposed key, no field
validation, and `.env.example` drift (documented env vars no code read). These
tests pin the fixes: the key never reprs, bad values are clamped not obeyed, and
Config.from_env() is the one place the environment is read.
"""
from __future__ import annotations

from dreamlayer.config import CONFIG, Config


# -- defaults + singleton ----------------------------------------------------

def test_singleton_is_a_config():
    assert isinstance(CONFIG, Config)
    assert CONFIG.llm_model == "gpt-4o-mini"
    assert 0.0 <= CONFIG.recall_min_confidence <= 1.0


def test_defaults_are_in_range():
    c = Config()
    assert c.llm_confidence_threshold == 0.60
    assert c.llm_timeout_s == 4.0
    assert c.capture_min_interval_ms == 4000


# -- the secret never reprs (repr=False) -------------------------------------

def test_api_key_never_appears_in_repr():
    c = Config(openai_api_key="sk-super-secret-123")
    text = repr(c)
    assert "sk-super-secret-123" not in text
    assert "openai_api_key" not in text
    # the value is still usable by code that asks for it directly
    assert c.openai_api_key == "sk-super-secret-123"


# -- validation clamps a bad value instead of silently obeying it ------------

def test_confidence_over_one_is_clamped():
    # a >1.0 floor would never reject — the exact silent-gate-disable the audit
    # named; it must clamp to 1.0, not pass through.
    c = Config(recall_min_confidence=5.0, proactive_min_confidence=-2.0)
    assert c.recall_min_confidence == 1.0
    assert c.proactive_min_confidence == 0.0


def test_negative_intervals_and_counts_floor_to_zero():
    c = Config(capture_min_interval_ms=-10, passive_ring_capacity=-1,
               passive_tick_interval_ms=-5, llm_word_threshold=-3)
    assert c.capture_min_interval_ms == 0
    assert c.passive_ring_capacity == 0
    assert c.passive_tick_interval_ms == 0
    assert c.llm_word_threshold == 0


def test_timeout_floored_to_a_positive_minimum():
    # a 0/negative timeout is a silent footgun (blocks or fails instantly)
    assert Config(llm_timeout_s=0.0).llm_timeout_s == 0.1
    assert Config(llm_timeout_s=-9.0).llm_timeout_s == 0.1
    assert Config(llm_timeout_s=8.0).llm_timeout_s == 8.0


def test_negative_retention_windows_floor_to_zero():
    c = Config(retention_hot_hours=-1.0, retention_warm_days=-4.0)
    assert c.retention_hot_hours == 0.0
    assert c.retention_warm_days == 0.0


# -- env precedence: env wins over default, exactly once ---------------------

def test_from_env_defaults_when_unset():
    c = Config.from_env(env={})
    assert c.llm_model == "gpt-4o-mini"
    assert c.llm_confidence_threshold == 0.60
    assert c.openai_api_key == ""


def test_from_env_overrides_model_and_confidence():
    c = Config.from_env(env={"OPENAI_MODEL": "gpt-4o",
                             "OPENAI_CONFIDENCE": "0.8",
                             "OPENAI_API_KEY": "sk-abc"})
    assert c.llm_model == "gpt-4o"
    assert c.llm_confidence_threshold == 0.8
    assert c.openai_api_key == "sk-abc"


def test_from_env_out_of_range_confidence_is_still_clamped():
    # env precedence still runs through __post_init__ validation
    c = Config.from_env(env={"OPENAI_CONFIDENCE": "9.0"})
    assert c.llm_confidence_threshold == 1.0


def test_from_env_unparseable_confidence_falls_back_to_default():
    # a mistyped value is ignored (logged), the default kept — never a crash
    c = Config.from_env(env={"OPENAI_CONFIDENCE": "not-a-number"})
    assert c.llm_confidence_threshold == 0.60


def test_from_env_blank_values_are_treated_as_unset():
    c = Config.from_env(env={"OPENAI_MODEL": "", "OPENAI_CONFIDENCE": "  "})
    assert c.llm_model == "gpt-4o-mini"
    assert c.llm_confidence_threshold == 0.60


def test_from_env_reads_the_process_environment_by_default(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini-env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-process")
    c = Config.from_env()
    assert c.llm_model == "gpt-4o-mini-env"
    assert c.openai_api_key == "sk-from-process"
