"""test_qr.py — the dependency-free pairing QR is spec-correct.

We can't visually scan in CI, so we prove the encoder two ways: the structural
patterns match the QR spec, and the data region round-trips back to the exact
bytes (which only holds if codeword placement, masking, interleaving and the
Reed–Solomon parity are all internally consistent).
"""
from __future__ import annotations

import pytest

from dreamlayer.ai_brain.server import qr


def _finder_ok(grid, r, c):
    # 7x7 finder: dark ring + 3x3 dark core
    for dr in range(7):
        for dc in range(7):
            edge = dr in (0, 6) or dc in (0, 6)
            core = 2 <= dr <= 4 and 2 <= dc <= 4
            want = 1 if (edge or core) else 0
            if grid[r + dr][c + dc] != want:
                return False
    return True


@pytest.mark.parametrize("text", [
    "dreamlayer:x",
    "dreamlayer:eyJicmFpbl91cmwiOiJodHRwOi8vMTkyLjE2OC4xLjQyOjc3NzcifQ",
    "dreamlayer:" + "A" * 120,                       # forces a higher version
])
def test_round_trips_to_original_bytes(text):
    grid = qr.encode_matrix(text)
    assert qr.decode_matrix(grid).decode("utf-8") == text


def test_structure_has_three_finders_and_timing():
    grid = qr.encode_matrix("dreamlayer:hello")
    n = len(grid)
    assert _finder_ok(grid, 0, 0)
    assert _finder_ok(grid, 0, n - 7)
    assert _finder_ok(grid, n - 7, 0)
    # timing rows alternate
    for i in range(8, n - 8):
        assert grid[6][i] == (1 if i % 2 == 0 else 0)
    # the mandatory dark module
    assert grid[n - 8][8] == 1


def test_version_scales_with_payload():
    small = qr.encode_matrix("dreamlayer:x")
    big = qr.encode_matrix("dreamlayer:" + "Z" * 150)
    assert len(big) > len(small)               # more data → bigger matrix


def test_svg_is_self_contained():
    svg = qr.to_svg("dreamlayer:pairme")
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "http://www.w3.org/2000/svg" in svg
    assert "<image" not in svg and "href" not in svg   # no external refs
