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


def _bch_format_codeword(data5: int) -> int:
    """The canonical 15-bit BCH(15,5) format word for a 5-bit value, built from
    scratch (generator 0x537, format mask 0x5412) so this is a genuinely
    independent oracle — it shares no code with the encoder under test."""
    g = 0x537
    code = data5 << 10
    d = code
    while d.bit_length() > 10:
        d ^= g << (d.bit_length() - 11)
    return (code | d) ^ 0x5412


# Spec cell positions (ISO/IEC 18004) for the two copies of the format word.
# index i in each list carries format bit i (LSB-first).
_FMT_TL = [(0, 8), (1, 8), (2, 8), (3, 8), (4, 8), (5, 8), (7, 8), (8, 8),
           (8, 7), (8, 5), (8, 4), (8, 3), (8, 2), (8, 1), (8, 0)]


def _read_format(grid, cells) -> int:
    word = 0
    for i, (r, c) in enumerate(cells):
        word |= (grid[r][c] & 1) << i
    return word


@pytest.mark.parametrize("text", [
    "dreamlayer:x",
    # the exact shape the iPhone Camera scans off the Live Lens panel:
    "https://192.168.1.42:7777/dreamlayer/live#c=123456",
    "http://192.168.1.42:7777/dreamlayer/live#t=" + "a" * 32,
])
def test_format_info_is_spec_decodable(text):
    """A conforming decoder (iPhone Camera / OpenCV / zxing) recovers the ECC
    level and mask from the BCH format word. If we lay those 15 bits down
    reversed, the word decodes to garbage and the whole symbol is unreadable —
    which is exactly what "the QR won't scan" looked like. This asserts the word
    at the spec cells is a real ECC-M codeword, independent of qr.py's reader."""
    valid_m = {_bch_format_codeword(mask): mask for mask in range(8)}  # ECC-M ⇒ data5==mask
    grid = qr.encode_matrix(text)
    n = len(grid)
    word = _read_format(grid, _FMT_TL)
    assert word in valid_m, (
        f"format word {word:#06x} is not a valid ECC-M BCH codeword — "
        "a real camera cannot decode this symbol")
    # the redundant second copy must carry the identical word
    second = [(8, n - 1), (8, n - 2), (8, n - 3), (8, n - 4), (8, n - 5),
              (8, n - 6), (8, n - 7), (8, n - 8),
              (n - 7, 8), (n - 6, 8), (n - 5, 8), (n - 4, 8), (n - 3, 8),
              (n - 2, 8), (n - 1, 8)]
    assert _read_format(grid, second) == word
