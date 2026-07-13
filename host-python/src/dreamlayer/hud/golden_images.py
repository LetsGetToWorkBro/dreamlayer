"""hud/golden_images.py

Golden-image regression suite for DreamLayer HUD cards.

Workflow
--------
1. GENERATE  — render each card via renderer.py, save PNG as golden reference.
2. DIFF      — re-render, pixel-diff against stored golden, report pass/fail.
3. SUITE     — run diff for all registered card keys; fail if any exceed tolerance.

Tolerances
----------
    PIXEL_TOLERANCE      = 8    per-channel absolute difference allowed
    CHANGED_PX_THRESHOLD = 0.02 fraction of total pixels allowed to differ

A card "passes" if fewer than 2% of its pixels differ by more than 8 per channel.

Usage
-----
    # Generate references (run once, commit the PNGs):
    python -m dreamlayer.hud.golden_images --generate --dir tests/golden_refs

    # Diff in CI:
    python -m dreamlayer.hud.golden_images --suite --dir tests/golden_refs

    # Programmatic:
    from dreamlayer.hud.golden_images import run_regression_suite
    results = run_regression_suite(golden_dir=Path("tests/golden_refs"))
    assert all(r.passed for r in results)
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageChops
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

from . import cards as C
from .renderer import CardRenderer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PIXEL_TOLERANCE      = 8      # per-channel max delta (0-255)
CHANGED_PX_THRESHOLD = 0.02   # 2% of pixels may differ

# Card keys eligible for golden regression (subset with deterministic layout)
DEFAULT_CARD_KEYS = [
    "ready",
    "saved_memory",
    "query_listening",
    "loading",
    "object_recall",
    "commitment_recall",
    "proactive_memory",
    "person_context",
    "privacy_veil",
    "error",
    "low_confidence",
    "commitment_drift",
    "time_scrub_node",
    "deviation_alert",
    "forget_last",
    "private_zone",
    "consent_required",
    "live_caption",
    # Halo Cinema v1
    "truth_gauge",
    "person_context_v2",
    "world_anchor",
    "synesthesia",
    "synesthesia_v2",
]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dataclass
class DiffResult:
    card_key:    str
    max_delta:   float         # highest per-pixel per-channel diff seen
    mean_delta:  float         # mean per-pixel per-channel diff
    changed_px:  int           # pixels exceeding PIXEL_TOLERANCE
    total_px:    int
    passed:      bool
    error:       Optional[str] = None

    @property
    def changed_fraction(self) -> float:
        return self.changed_px / self.total_px if self.total_px else 0.0

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] {self.card_key:25s}  "
            f"changed={self.changed_px}/{self.total_px} "
            f"({self.changed_fraction:.1%})  "
            f"max_delta={self.max_delta:.1f}  mean={self.mean_delta:.2f}"
        )


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _render_card(card_key: str) -> "Image.Image":
    """Render a card from ALL_SAMPLES to a PIL Image."""
    if not _PIL_AVAILABLE:
        raise RuntimeError("Pillow is required for golden image testing")
    card = C.ALL_SAMPLES.get(card_key)
    if card is None:
        raise KeyError(f"Unknown card key: {card_key!r}")
    r = CardRenderer()
    return r.render(card)


def _golden_path(card_key: str, golden_dir: Path) -> Path:
    return golden_dir / f"{card_key}.png"


def generate_golden(
    card_key: str,
    golden_dir: Path,
    overwrite: bool = True,
) -> Path:
    """Render card and save as golden PNG reference.

    Returns the path written.
    """
    golden_dir = Path(golden_dir)
    golden_dir.mkdir(parents=True, exist_ok=True)
    out = _golden_path(card_key, golden_dir)
    if out.exists() and not overwrite:
        return out
    img = _render_card(card_key)
    img.save(out)
    return out


def diff_against_golden(
    card_key: str,
    golden_dir: Path,
    pixel_tolerance: int = PIXEL_TOLERANCE,
    changed_px_threshold: float = CHANGED_PX_THRESHOLD,
) -> DiffResult:
    """Re-render card and pixel-diff against stored golden PNG.

    Returns a DiffResult with pass/fail and metrics.
    """
    golden_dir = Path(golden_dir)
    golden_path = _golden_path(card_key, golden_dir)

    if not _PIL_AVAILABLE:
        return DiffResult(
            card_key=card_key, max_delta=0, mean_delta=0,
            changed_px=0, total_px=1, passed=False,
            error="Pillow not available",
        )

    if not golden_path.exists():
        return DiffResult(
            card_key=card_key, max_delta=0, mean_delta=0,
            changed_px=0, total_px=1, passed=False,
            error=f"Golden not found: {golden_path}",
        )

    try:
        golden_img = Image.open(golden_path).convert("RGB")
        current_img = _render_card(card_key).convert("RGB")

        if golden_img.size != current_img.size:
            current_img = current_img.resize(golden_img.size, Image.LANCZOS)

        diff = ImageChops.difference(golden_img, current_img)
        # (r,g,b) per pixel via tobytes() — getdata() is removed in Pillow 14
        raw = diff.tobytes()
        pixels = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
        total_px = len(pixels)

        max_delta = 0.0
        sum_delta = 0.0
        changed = 0
        for px in pixels:
            ch_max = max(px)
            ch_mean = sum(px) / 3
            if ch_max > max_delta:
                max_delta = ch_max
            sum_delta += ch_mean
            if ch_max > pixel_tolerance:
                changed += 1

        mean_delta = sum_delta / total_px if total_px else 0.0
        passed = (changed / total_px) <= changed_px_threshold

        return DiffResult(
            card_key=card_key,
            max_delta=float(max_delta),
            mean_delta=float(mean_delta),
            changed_px=changed,
            total_px=total_px,
            passed=passed,
        )
    except Exception as exc:
        return DiffResult(
            card_key=card_key, max_delta=0, mean_delta=0,
            changed_px=0, total_px=1, passed=False,
            error=str(exc),
        )


def run_regression_suite(
    card_keys: Optional[list[str]] = None,
    golden_dir: Path = Path("tests/golden_refs"),
    pixel_tolerance: int = PIXEL_TOLERANCE,
    changed_px_threshold: float = CHANGED_PX_THRESHOLD,
) -> list[DiffResult]:
    """Run full regression suite; return list of DiffResult."""
    keys = card_keys or DEFAULT_CARD_KEYS
    return [
        diff_against_golden(
            k, golden_dir,
            pixel_tolerance=pixel_tolerance,
            changed_px_threshold=changed_px_threshold,
        )
        for k in keys
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DreamLayer golden-image regression")
    parser.add_argument("--generate", action="store_true", help="Generate/overwrite golden PNGs")
    parser.add_argument("--diff",     metavar="KEY",       help="Diff a single card key")
    parser.add_argument("--suite",    action="store_true", help="Run full regression suite")
    parser.add_argument("--dir",      default="tests/golden_refs", help="Golden image directory")
    args = parser.parse_args()

    golden_dir = Path(args.dir)

    if args.generate:
        for key in DEFAULT_CARD_KEYS:
            try:
                p = generate_golden(key, golden_dir)
                print(f"  generated  {p}")
            except Exception as e:
                print(f"  ERROR {key}: {e}")

    elif args.diff:
        result = diff_against_golden(args.diff, golden_dir)
        print(result)
        sys.exit(0 if result.passed else 1)

    elif args.suite:
        results = run_regression_suite(golden_dir=golden_dir)
        failed = [r for r in results if not r.passed]
        for r in results:
            print(r)
        if failed:
            print(f"\n{len(failed)} card(s) failed regression.")
            sys.exit(1)
        else:
            print(f"\nAll {len(results)} cards passed.")

    else:
        parser.print_help()
