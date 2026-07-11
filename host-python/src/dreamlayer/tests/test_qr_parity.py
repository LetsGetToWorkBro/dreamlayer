"""The vendored QR encoder (landing/assets/lens/qr.js) is verified bit-for-bit
against the reference `qrcode` library — so a share QR is provably scannable,
not just plausible. Skips when node or qrcode aren't present.

Byte mode only: the builder QR-encodes base64url share links, which always
contain lowercase / `-` / `_`, so QR byte mode is the only mode in play.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

QR_JS = Path(__file__).resolve().parents[4] / "landing" / "assets" / "lens" / "qr.js"

qrcode = pytest.importorskip("qrcode")
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node not installed")


def _ref_matrix(text: str, mask: int) -> list[list[int]]:
    from qrcode.util import QRData, MODE_8BIT_BYTE
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L,
                      box_size=1, border=0, mask_pattern=mask)
    q.add_data(QRData(text.encode(), mode=MODE_8BIT_BYTE))
    q.make(fit=True)
    return [[1 if c else 0 for c in row] for row in q.get_matrix()]


def _mine_matrix(text: str, mask: int) -> list[list[int]]:
    out = subprocess.run(
        ["node", "-e",
         "var Q=require('./qr.js');"
         "console.log(JSON.stringify(Q.matrix(process.argv[1],{ecl:'L',mask:+process.argv[2]})"
         ".map(function(r){return r.map(function(v){return v?1:0;});})));",
         text, str(mask)],
        cwd=QR_JS.parent, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# a short code, a base64url-ish blob, and a payload big enough to push the
# version up — each across all eight masks
@pytest.mark.parametrize("text", [
    "hello-world-123",
    "eyJ2IjoxLCJmIjp7InNjZW5lcyI6e319fQ",
    "aB9-_z" * 90,
])
@pytest.mark.parametrize("mask", list(range(8)))
def test_qr_matches_reference_bit_for_bit(text, mask):
    assert _mine_matrix(text, mask) == _ref_matrix(text, mask)
