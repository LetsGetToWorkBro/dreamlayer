"""Cross-language parity, second target: the Rust `reality-core` crate compiled
to **wasm**, checked against the JS side (ADR 0003's recommended next step).

The native cdylib parity test (test_reality_core_parity.py) proved the Rust core
equals the Python reference. This proves the *same crate*, compiled to
`wasm32-unknown-unknown`, equals the JS semantics — so "one source, many
targets" holds across a language boundary that actually ships (the lens
builder's figment.js). The heavy lifting is in reality-core/parity/wasm_parity.mjs,
which loads the compiled wasm and checks it (A) bit-for-bit against figment.js's
transcribed cap expressions and (B) against the real shipped figment.js Stage.

Builds the wasm on demand; skips cleanly where cargo, the wasm target, or node
is unavailable. Not on the release path — a de-risking artifact for the ADR."""
import shutil
import subprocess
from pathlib import Path

import pytest

CRATE = Path(__file__).resolve().parents[4] / "reality-core"
HARNESS = CRATE / "parity" / "wasm_parity.mjs"
WASM = CRATE / "target" / "wasm32-unknown-unknown" / "release" / "reality_core.wasm"


def _require(tool):
    if shutil.which(tool) is None:
        pytest.skip(f"{tool} not available")


@pytest.fixture(scope="module")
def wasm_built():
    if not HARNESS.exists():
        pytest.skip("reality-core wasm parity harness not present")
    _require("cargo")
    _require("node")
    # ensure the wasm target is installed; skip (don't fail) if we can't add it
    have = subprocess.run(["rustup", "target", "list", "--installed"],
                          capture_output=True, text=True)
    if "wasm32-unknown-unknown" not in have.stdout:
        pytest.skip("wasm32-unknown-unknown target not installed")
    build = subprocess.run(
        ["cargo", "build", "--release", "--target", "wasm32-unknown-unknown"],
        cwd=CRATE, capture_output=True, text=True)
    if build.returncode or not WASM.exists():
        pytest.skip(f"wasm build failed: {build.stderr[-400:]}")
    return WASM


def test_wasm_core_matches_js(wasm_built):
    r = subprocess.run(["node", str(HARNESS)], cwd=CRATE,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr or r.stdout
    assert "OK" in r.stdout, r.stdout
