"""PR4 privacy/security/reliability seam tests — fallback paths + property and
benchmark checks. Optional deps are absent in CI; markers deselected there.
"""
from __future__ import annotations
import asyncio

import pytest


# --- privacy: PII redaction (regex fallback) + capture guard -----------------
def test_pii_redactor_fallback():
    from dreamlayer.memory.pii_presidio import PiiRedactor

    class _Veil:
        def __init__(self, on): self._on = on
        def allow_capture(self): return self._on

    r = PiiRedactor()
    red = r.redact("email me at a@b.com or call 555-123-4567 pin 998877")
    assert "<EMAIL>" in red and "<PHONE>" in red and "<NUM>" in red
    assert r.redact_for_write("secret 1234567", privacy=_Veil(True)) is not None
    assert r.redact_for_write("secret", privacy=_Veil(False)) is None   # veil down


# --- privacy: MemoryEvent makes a veiled write impossible at construction ----
def test_memory_event_type_invariant():
    from dreamlayer.memory.models_pydantic import MemoryEvent, PrivacyViolation
    ok = MemoryEvent(kind="Promise", summary="lease", allowed=True)
    assert ok.summary == "lease"
    with pytest.raises(PrivacyViolation):
        MemoryEvent(kind="Promise", summary="lease", allowed=False)


# --- security: signer round-trips (Ed25519) + rejects tampering --------------
def test_signer_roundtrip_and_tamper():
    from dreamlayer.reality_compiler.sign_crypto import Signer, SigningError, content_hash
    s = Signer(key=b"x" * 32)
    payload = {"figment": "round-timer", "run_sec": 180}
    sig = s.sign(payload)
    if s.available:                       # real Ed25519 signatures verify…
        assert s.verify(payload, sig) is True
        assert s.verify({"figment": "round-timer", "run_sec": 181}, sig) is False
    else:                                 # …but the HMAC fallback is never trusted
        assert s.verify(payload, sig) is False
    with pytest.raises(SigningError):
        s.verify_or_raise(payload, "deadbeef")
    assert len(content_hash(payload)) == 16


# --- security: the HMAC fallback signature is never trusted (revert-failing) --
def test_hmac_fallback_verify_is_refused(monkeypatch):
    """Without `cryptography`, Signer can only emit a symmetric HMAC, which
    proves no authorship and — under the old public default key — was forgeable
    by anyone. verify()/verify_or_raise() must REFUSE the fallback, never
    compare-and-trust it. Reverting the primitive (a baked-in default key and/or
    hmac.compare_digest in verify) turns this red."""
    import hashlib
    import hmac as _hmac
    from dreamlayer.reality_compiler import sign_crypto
    from dreamlayer.reality_compiler.sign_crypto import Signer, SigningError, _canonical

    monkeypatch.setattr(sign_crypto, "_HAS_CRYPTO", False)
    payload = {"figment": "round-timer", "run_sec": 180}

    # 1) A genuine HMAC produced by this very signer is still refused on the
    #    fallback path — catches a revert of verify() to hmac.compare_digest.
    s = Signer(key=b"k" * 32)
    assert s._pub is None                             # fallback path is live
    good_hmac = s.sign(payload)
    assert s.verify(payload, good_hmac) is False
    with pytest.raises(SigningError):
        s.verify_or_raise(payload, good_hmac)

    # 2) The original footgun: a signature forged with the OLD public default
    #    key (sha256(b"dreamlayer-session")) must not verify against a keyless
    #    Signer — pre-fix, Signer() adopted that constant and compared with it.
    forged_key = hashlib.sha256(b"dreamlayer-session").digest()
    forged_sig = _hmac.new(forged_key, _canonical(payload),
                           hashlib.sha256).hexdigest()
    assert Signer().verify(payload, forged_sig) is False

    # 3) A keyless Signer must not silently adopt that public constant as its
    #    key — catches a revert of the default back to the baked-in constant.
    assert Signer()._key != forged_key


# --- reliability: anyio veil scope cancels all tasks on stop (asyncio path) ---
def test_concurrency_veil_stop():
    from dreamlayer.orchestrator.concurrency_anyio import run_until_veil

    async def _main():
        stop = asyncio.Event()
        ran = {"n": 0}

        async def worker():
            try:
                while True:
                    ran["n"] += 1
                    await asyncio.sleep(0.005)
            except asyncio.CancelledError:
                raise

        async def dropper():
            await asyncio.sleep(0.03)
            stop.set()

        await asyncio.gather(
            run_until_veil([worker], stop),
            dropper(),
        )
        return ran["n"]

    n = asyncio.run(_main())
    assert n > 0   # worker ran, then the veil cancelled it (no hang)


# --- reliability: typed pipeline threads stages and stops on failure ---------
def test_stage_pipeline():
    from dreamlayer.reality_compiler.pipeline_pydanticai import StagePipeline
    good = StagePipeline([("double", lambda v: v * 2), ("inc", lambda v: v + 1)])
    r = good.run(3)
    assert r.ok and r.value == 7 and r.trace == ["double", "inc"]

    def _boom(v): raise ValueError("nope")
    bad = StagePipeline([("double", lambda v: v * 2), ("boom", _boom)])
    r2 = bad.run(3)
    assert not r2.ok and r2.failed_at == "boom" and r2.trace == ["double"]


# --- property-based (hypothesis): signer verifies its own signatures ----------
try:
    from hypothesis import given, strategies as st
    _HAS_HYP = True
except ImportError:
    _HAS_HYP = False


if _HAS_HYP:
    @given(st.text(min_size=0, max_size=200))
    def test_signer_property(text):
        from dreamlayer.reality_compiler.sign_crypto import Signer
        s = Signer(key=b"k" * 32)
        payload = {"t": text}
        # Ed25519 verifies its own signatures; the HMAC fallback is refused.
        assert s.verify(payload, s.sign(payload)) is s.available


# --- benchmark: signing stays well under budget (deselected in CI) -----------
@pytest.mark.benchmark
def test_sign_latency_budget():
    import time
    from dreamlayer.reality_compiler.sign_crypto import Signer
    s = Signer(key=b"z" * 32)
    payload = {"figment": "x" * 200}
    t0 = time.perf_counter()
    for _ in range(50):
        s.verify(payload, s.sign(payload))
    dur = (time.perf_counter() - t0) / 50
    assert dur < 0.010   # 10ms budget per sign+verify
