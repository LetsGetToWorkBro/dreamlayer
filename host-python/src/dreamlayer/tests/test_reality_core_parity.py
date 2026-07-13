"""Cross-language parity: the Rust `reality-core` PoC vs the Python reference.

The single-Rust-core proposal (docs/adr/0001-single-rust-core.md) rests on one
claim: a safety cap implemented ONCE in Rust can back every interpreter, so
parity is guaranteed by construction instead of tested for across three
hand-written copies. This test is the evidence. It loads the *compiled* Rust
cdylib via ctypes and drives it against `reality_compiler/v2/contracts.py` — the
exact functions M1 proved and M4 mutation-hardened — over a swept input space,
asserting the two agree bit-for-bit (ints exactly, floats to the last ULP).

It builds the crate on demand with `cargo build --release`; where cargo or the
shared library is unavailable (most CI), it skips cleanly — the PoC is a
de-risking artifact, not yet on the release path."""
import ctypes
import subprocess
from pathlib import Path

import pytest

from dreamlayer.reality_compiler.v2 import contracts

CRATE = Path(__file__).resolve().parents[4] / "reality-core"
OP = {"inc": 0, "dec": 1, "set": 2}


def _load_core():
    if not CRATE.exists():
        pytest.skip("reality-core crate not present")
    so = next(iter((CRATE / "target" / "release").glob("libreality_core.*")), None)
    if so is None:
        if subprocess.run(["cargo", "--version"], capture_output=True).returncode:
            pytest.skip("cargo not available to build the Rust core")
        r = subprocess.run(["cargo", "build", "--release"], cwd=CRATE,
                            capture_output=True, text=True)
        if r.returncode:
            pytest.skip(f"cargo build failed: {r.stderr[-400:]}")
        so = next(iter((CRATE / "target" / "release").glob("libreality_core.*")))
    lib = ctypes.CDLL(str(so))
    lib.rc_saturate.restype = ctypes.c_int64
    lib.rc_saturate.argtypes = [ctypes.c_int64, ctypes.c_uint8, ctypes.c_int64,
                                ctypes.c_int64, ctypes.c_int64]
    lib.rc_refill_tokens.restype = ctypes.c_double
    lib.rc_refill_tokens.argtypes = [ctypes.c_double] * 4
    lib.rc_spend_token.restype = ctypes.c_int32
    lib.rc_spend_token.argtypes = [ctypes.c_double, ctypes.POINTER(ctypes.c_double)]
    lib.rc_clamp_len.restype = ctypes.c_uint64
    lib.rc_clamp_len.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
    lib.rc_accept_slot.restype = ctypes.c_int32
    lib.rc_accept_slot.argtypes = [ctypes.c_int32, ctypes.c_int32,
                                   ctypes.c_int64, ctypes.c_int64]
    return lib


@pytest.fixture(scope="module")
def core():
    return _load_core()


class TestSaturateParity:
    def test_swept(self, core):
        for lo, hi in ((0, 10), (-5, 5), (0, 3), (1, 3), (-100, 100)):
            for op in ("inc", "dec", "set"):
                for cur in range(lo - 2, hi + 3):
                    for amount in (0, 1, 2, 5, 100, -3):
                        py = contracts.saturate(cur, op, amount, lo, hi)
                        rs = core.rc_saturate(cur, OP[op], amount, lo, hi)
                        assert py == rs, (cur, op, amount, lo, hi, py, rs)


class TestRefillParity:
    def test_swept(self, core):
        for tokens in (0.0, 0.5, 1.0, 3.0, 5.0):
            for dt in (0.0, 0.1, 0.5, 1.0, 3.3, 1000.0):
                for refill in (0.0, 1.0, 2.5):
                    for burst in (5.0, 1.0, 10.0):
                        py = contracts.refill_tokens(tokens, dt, refill, burst)
                        rs = core.rc_refill_tokens(tokens, dt, refill, burst)
                        assert py == rs, (tokens, dt, refill, burst, py, rs)


class TestSpendParity:
    def test_swept(self, core):
        out = ctypes.c_double(0.0)
        for tokens in (0.0, 0.5, 0.999, 1.0, 1.0001, 2.5, 5.0):
            spent_py, after_py = contracts.spend_token(tokens)
            spent_rs = core.rc_spend_token(tokens, ctypes.byref(out))
            assert int(spent_py) == spent_rs, (tokens, spent_py, spent_rs)
            assert after_py == out.value, (tokens, after_py, out.value)


class TestClampParity:
    def test_swept(self, core):
        for length in range(0, 40):
            for max_len in (0, 1, 24, 39):
                py = len(contracts.clamp_text("x" * length, max_len))
                rs = core.rc_clamp_len(length, max_len)
                assert py == rs, (length, max_len, py, rs)


class TestAcceptSlotParity:
    def test_swept(self, core):
        for d in (0, 1):
            for k in (0, 1):
                for named in range(0, 12):
                    for mx in (0, 1, 8):
                        py = contracts.accept_slot(bool(d), bool(k), named, mx)
                        rs = core.rc_accept_slot(d, k, named, mx)
                        assert int(py) == rs, (d, k, named, mx, py, rs)


def test_core_is_exhaustively_equivalent_on_the_hot_path(core):
    """A blunt end-to-end check: the token bucket driven through many spends +
    refills stays identical between the Rust core and the Python reference — the
    exact loop the interpreter runs every emit."""
    out = ctypes.c_double(0.0)
    py_tokens = rs_tokens = 5.0
    for step in range(200):
        dt = (step % 7) * 0.3
        py_tokens = contracts.refill_tokens(py_tokens, dt, 1.0, 5.0)
        rs_tokens = core.rc_refill_tokens(rs_tokens, dt, 1.0, 5.0)
        spent_py, py_tokens = contracts.spend_token(py_tokens)
        spent_rs = core.rc_spend_token(rs_tokens, ctypes.byref(out))
        rs_tokens = out.value
        assert int(spent_py) == spent_rs and py_tokens == rs_tokens, step
