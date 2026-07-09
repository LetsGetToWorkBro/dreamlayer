"""Asymmetric signing (cryptography) for Figments / provenance / registry
artifacts — Ed25519 signatures over canonical JSON.

ADD-alongside: new sibling to v2/signer.py (SessionSigner, HMAC-stdlib, is
untouched). Mirrors its sign/verify/verify_or_raise surface but on a generic
dict|bytes payload. Lazy-imports cryptography (extras group `privacy`); when
absent it falls back to the same stdlib HMAC scheme SessionSigner uses, so
signing/verification always works.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging

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
    """Ed25519 when available, else HMAC-SHA256 (stdlib). `key` is 32 bytes."""
    available = _HAS_CRYPTO

    def __init__(self, key: bytes | None = None):
        self._key = key or hashlib.sha256(b"dreamlayer-session").digest()
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
        data = _canonical(payload)
        if self._pub is not None:
            try:
                self._pub.verify(bytes.fromhex(signature), data)
                return True
            except (InvalidSignature, ValueError):
                return False
        expected = hmac.new(self._key, data, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_or_raise(self, payload, signature: str) -> None:
        if not self.verify(payload, signature):
            raise SigningError("signature verification failed")


def content_hash(payload) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()[:16]
