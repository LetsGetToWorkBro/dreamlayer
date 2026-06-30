"""Tests for golden-image regression infrastructure.

Tests do NOT require pre-generated golden PNGs to pass — they test
the generate/diff/suite API surface and logic contracts.
Actual pixel comparison requires running --generate first.
"""
import tempfile
from pathlib import Path

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from memoscape.hud.golden_images import (
    generate_golden,
    diff_against_golden,
    run_regression_suite,
    DiffResult,
    DEFAULT_CARD_KEYS,
    PIXEL_TOLERANCE,
    CHANGED_PX_THRESHOLD,
)


# ---------------------------------------------------------------------------
# DiffResult dataclass
# ---------------------------------------------------------------------------

def test_diff_result_changed_fraction():
    r = DiffResult(
        card_key="ready", max_delta=0, mean_delta=0,
        changed_px=100, total_px=5000, passed=True
    )
    assert abs(r.changed_fraction - 0.02) < 1e-6

def test_diff_result_str_pass():
    r = DiffResult(
        card_key="ready", max_delta=2.0, mean_delta=0.5,
        changed_px=10, total_px=65536, passed=True
    )
    assert "PASS" in str(r)
    assert "ready" in str(r)

def test_diff_result_str_fail():
    r = DiffResult(
        card_key="error", max_delta=100.0, mean_delta=30.0,
        changed_px=5000, total_px=65536, passed=False
    )
    assert "FAIL" in str(r)


# ---------------------------------------------------------------------------
# generate_golden + diff_against_golden round-trip (requires PIL)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")
def test_generate_and_diff_passes():
    """Generate a golden then diff against itself — must pass."""
    with tempfile.TemporaryDirectory() as tmpdir:
        golden_dir = Path(tmpdir)
        key = "ready"
        generate_golden(key, golden_dir)
        result = diff_against_golden(key, golden_dir)
        assert result.passed, f"Self-diff should always pass: {result}"
        assert result.max_delta == 0.0
        assert result.changed_px == 0


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")
def test_diff_fails_when_golden_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = diff_against_golden("ready", Path(tmpdir))
        assert not result.passed
        assert result.error is not None


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")
def test_diff_fails_on_pixel_delta():
    """Manually corrupt a golden PNG and verify diff detects it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        golden_dir = Path(tmpdir)
        key = "ready"
        generate_golden(key, golden_dir)

        # Corrupt the golden: fill with white noise
        import random
        img = Image.new("RGB", (256, 256))
        pixels = [(random.randint(0, 255),) * 3 for _ in range(256 * 256)]
        img.putdata(pixels)
        img.save(golden_dir / f"{key}.png")

        result = diff_against_golden(key, golden_dir, changed_px_threshold=0.0)
        assert not result.passed


# ---------------------------------------------------------------------------
# DEFAULT_CARD_KEYS completeness
# ---------------------------------------------------------------------------

def test_default_card_keys_include_new_cards():
    for key in ("forget_last", "private_zone", "consent_required", "live_caption"):
        assert key in DEFAULT_CARD_KEYS, f"Missing from DEFAULT_CARD_KEYS: {key}"

def test_default_card_keys_all_in_all_samples():
    from memoscape.hud.cards import ALL_SAMPLES
    for key in DEFAULT_CARD_KEYS:
        assert key in ALL_SAMPLES, f"DEFAULT_CARD_KEYS has {key!r} but ALL_SAMPLES does not"


# ---------------------------------------------------------------------------
# run_regression_suite returns one result per key (with no golden dir)
# ---------------------------------------------------------------------------

def test_suite_returns_result_per_key():
    with tempfile.TemporaryDirectory() as tmpdir:
        results = run_regression_suite(
            card_keys=["ready", "loading"],
            golden_dir=Path(tmpdir),
        )
    assert len(results) == 2
    assert all(isinstance(r, DiffResult) for r in results)
    # Without goldens, all fail
    assert all(not r.passed for r in results)
