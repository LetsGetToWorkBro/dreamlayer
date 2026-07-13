"""Tests for DismissalTracker adaptive confidence feedback loop."""
import tempfile
from pathlib import Path

from dreamlayer.orchestrator.adaptive_confidence import (
    DismissalTracker,
    reset_global_tracker,
    get_tracker,
)


def _shown(card_type: str) -> dict:
    return {"t": "TEL", "event": "CARD_SHOWN", "card_type": card_type}

def _dismissed(card_type: str) -> dict:
    return {"t": "TEL", "event": "CARD_DISMISSED", "card_type": card_type}


# ---------------------------------------------------------------------------
# Basic ingestion
# ---------------------------------------------------------------------------

def test_empty_dismissal_rate():
    t = DismissalTracker(persist=False)
    assert t.dismissal_rate("ObjectRecallCard") == 0.0

def test_shown_count_increments():
    t = DismissalTracker(persist=False)
    t.on_telemetry_event(_shown("ObjectRecallCard"))
    t.on_telemetry_event(_shown("ObjectRecallCard"))
    assert t.shown_count("ObjectRecallCard") == 2

def test_dismissal_rate_calculation():
    t = DismissalTracker(persist=False)
    for _ in range(4):
        t.on_telemetry_event(_shown("ObjectRecallCard"))
    for _ in range(3):
        t.on_telemetry_event(_dismissed("ObjectRecallCard"))
    assert abs(t.dismissal_rate("ObjectRecallCard") - 0.75) < 0.01

def test_ignores_non_tel_events():
    t = DismissalTracker(persist=False)
    t.on_telemetry_event({"t": "BLE", "event": "CARD_SHOWN", "card_type": "ReadyCard"})
    assert t.shown_count("ReadyCard") == 0

def test_ignores_unknown_events():
    t = DismissalTracker(persist=False)
    t.on_telemetry_event({"t": "TEL", "event": "SOMETHING_ELSE", "card_type": "ReadyCard"})
    assert t.shown_count("ReadyCard") == 0


# ---------------------------------------------------------------------------
# Threshold adjustment
# ---------------------------------------------------------------------------

def test_threshold_not_raised_below_min_samples():
    t = DismissalTracker(persist=False)
    # Only 2 shown (< MIN_SAMPLES=3), both dismissed
    t.on_telemetry_event(_shown("LowConfidenceCard"))
    t.on_telemetry_event(_dismissed("LowConfidenceCard"))
    t.on_telemetry_event(_dismissed("LowConfidenceCard"))
    base = 0.45
    assert t.suggested_threshold("LowConfidenceCard", base) == base

def test_threshold_not_raised_below_high_dismiss_rate():
    t = DismissalTracker(persist=False)
    # 5 shown, 2 dismissed = 40% rate < HIGH_DISMISS_RATE
    for _ in range(5):
        t.on_telemetry_event(_shown("ProactiveMemoryCard"))
    for _ in range(2):
        t.on_telemetry_event(_dismissed("ProactiveMemoryCard"))
    assert t.suggested_threshold("ProactiveMemoryCard", 0.45) == 0.45

def test_threshold_raised_when_high_dismiss_rate():
    t = DismissalTracker(persist=False)
    for _ in range(5):
        t.on_telemetry_event(_shown("LowConfidenceCard"))
    for _ in range(5):
        t.on_telemetry_event(_dismissed("LowConfidenceCard"))
    raised = t.suggested_threshold("LowConfidenceCard", 0.45)
    assert raised > 0.45
    assert raised <= 0.95

def test_threshold_hard_cap():
    t = DismissalTracker(persist=False)
    for _ in range(10):
        t.on_telemetry_event(_shown("LowConfidenceCard"))
        t.on_telemetry_event(_dismissed("LowConfidenceCard"))
    assert t.suggested_threshold("LowConfidenceCard", 0.90) <= 0.95


# ---------------------------------------------------------------------------
# Sliding window cap
# ---------------------------------------------------------------------------

def test_window_does_not_exceed_max():
    t = DismissalTracker(window_size=5, persist=False)
    for _ in range(20):
        t.on_telemetry_event(_shown("ReadyCard"))
    assert len(t.window_snapshot()) == 5


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------

def test_persistence_round_trip():
    with tempfile.TemporaryDirectory() as tmpdir:
        log = Path(tmpdir) / "dismissal_log.json"
        t = DismissalTracker(persist=True, log_path=log)
        t.on_telemetry_event(_shown("ObjectRecallCard"))
        t.on_telemetry_event(_dismissed("ObjectRecallCard"))

        t2 = DismissalTracker(persist=True, log_path=log)
        assert t2.shown_count("ObjectRecallCard") == 1
        assert t2.dismissal_rate("ObjectRecallCard") == 1.0


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

def test_get_tracker_returns_same_instance():
    reset_global_tracker()
    a = get_tracker(persist=False)
    b = get_tracker(persist=False)
    assert a is b
    reset_global_tracker()
