"""Asymmetric signing (cryptography) for Figments / provenance / registry
artifacts — Ed25519 signatures over canonical JSON.

ADD-alongside: new sibling to v2/signer.py (SessionSigner, HMAC-stdlib, is
untouched). Mirrors its sign/verify/verify_or_raise surface but on a generic
dict|bytes payload. Lazy-imports cryptography (extras group `privacy`). When it
is absent, sign() can still emit an HMAC, but verify() REFUSES that fallback
(returns False): a symmetric MAC is not a provenance signature — the verifier
holds the same secret the signer used, so a "match" attests nothing about
authorship and, with any shared/guessable key, is forgeable. Trustworthy
verification therefore requires the Ed25519 path, matching verify_detached()
which returns None on the same fallback (audit 2026-07-14).
"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import os

log = logging.getLogger("dreamlayer.sign_crypto")

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey)  # type: ignore
    from cryptography.exceptions import InvalidSignature  # type: ignore
    _HAS_CRYPTO = True
except BaseException:  # ImportError, or a broken native install (pyo3 PanicException)
    _HAS_CRYPTO = False


class SigningError(Exception):
    pass


def _canonical(payload) -> bytes:
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class Signer:
    """Ed25519 signer/verifier. `key` is 32 bytes. Without the `cryptography`
    extra it can still HMAC-sign, but verify() refuses that fallback — a
    symmetric MAC proves no authorship — so a "verified" HMAC is never trusted."""
    available = _HAS_CRYPTO

    def __init__(self, key: bytes | None = None):
        # A missing key gets a PER-INSTANCE RANDOM secret, never a baked-in
        # constant. The old default — sha256(b"dreamlayer-session") — is public
        # in this source, so on the HMAC fallback (no `cryptography` extra)
        # anyone could forge a signature that verifies. No caller constructs
        # Signer() without a key today, so this only closes the latent footgun
        # (audit 2026-07-14): a future keyless Signer can no longer be forged.
        self._key = key or os.urandom(32)
        self._priv = None
        self._pub = None
        if _HAS_CRYPTO:
            try:
                self._priv = Ed25519PrivateKey.from_private_bytes(self._key[:32])
                self._pub = self._priv.public_key()
            except Exception as exc:
                log.warning("[sign_crypto] key load failed: %s; hmac fallback", exc)
                self._priv = None

    def sign(self, payload) -> str:
        data = _canonical(payload)
        if self._priv is not None:
            return self._priv.sign(data).hex()
        return hmac.new(self._key, data, hashlib.sha256).hexdigest()

    def verify(self, payload, signature: str) -> bool:
        """True only on a genuine Ed25519 verification. On the HMAC fallback
        (no `cryptography` extra, or a key that would not load as Ed25519) there
        is no asymmetric signature to check: the "signature" is a symmetric MAC
        this verifier could equally have produced, so a match proves nothing
        about authorship and, with any shared/guessable key, is forgeable.
        Refuse (return False = unverifiable) rather than hand back a misleading
        True — real provenance needs the Ed25519 path. Mirrors verify_detached(),
        which returns None on the same fallback (audit 2026-07-14)."""
        data = _canonical(payload)
        if self._pub is not None:
            try:
                self._pub.verify(bytes.fromhex(signature), data)
                return True
            except (InvalidSignature, ValueError):
                return False
        log.warning("[sign_crypto] verify refused: HMAC fallback cannot attest "
                    "provenance (install the 'privacy' extra for Ed25519)")
        return False

    def verify_or_raise(self, payload, signature: str) -> None:
        if not self.verify(payload, signature):
            raise SigningError("signature verification failed")

    @property
    def public_key_hex(self) -> str:
        """Raw Ed25519 public key, hex — the identity an author publishes so
        anyone can verify without the private seed. Empty on the HMAC
        fallback (symmetric keys have no public half to publish)."""
        if self._pub is None:
            return ""
        from cryptography.hazmat.primitives import serialization
        raw = self._pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        return raw.hex()


def verify_detached(payload, signature_hex: str,
                    public_key_hex: str) -> bool | None:
    """Verify an author signature with ONLY the public key.

    Returns True/False on a real verification, or None when the
    `cryptography` extra isn't installed — callers must treat None as
    *unverifiable*, never as valid.
    """
    if not _HAS_CRYPTO:
        return None
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        pub.verify(bytes.fromhex(signature_hex), _canonical(payload))
        return True
    except (InvalidSignature, ValueError):
        return False


def content_hash(payload) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()[:16]
