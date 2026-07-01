"""v2/signer.py — session-key signing for Figments.

Every kept Figment is signed with a per-install session key
(HMAC-SHA256 over the canonical JSON). The deployer refuses anything
unsigned, tampered, or revoked. The key is generated on first use, lives
in the vault directory with 0600 permissions, and never leaves the phone.

Stdlib only — no cryptography dependency for the offline path.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

from .figment import Figment

KEY_FILE = "session.key"


class SigningError(ValueError):
    """Signature missing, malformed, or failed verification."""


class SessionSigner:
    """HMAC-SHA256 signer bound to one install's session key."""

    def __init__(self, key_dir: Path) -> None:
        self._key_path = Path(key_dir) / KEY_FILE
        self._key = self._load_or_create()

    def _load_or_create(self) -> bytes:
        if self._key_path.exists():
            return bytes.fromhex(self._key_path.read_text().strip())
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        self._key_path.write_text(key.hex())
        os.chmod(self._key_path, 0o600)
        return key

    def sign(self, fig: Figment) -> str:
        payload = fig.canonical_json().encode("utf-8")
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(self, fig: Figment, signature: str) -> bool:
        try:
            expected = self.sign(fig)
        except Exception:
            return False
        return hmac.compare_digest(expected, signature or "")

    def verify_or_raise(self, fig: Figment, signature: str) -> None:
        if not self.verify(fig, signature):
            raise SigningError(
                f"figment {fig.id} failed signature verification — "
                "not signed by this install's session key")


def content_hash(fig: Figment) -> str:
    """Key-independent digest, echoed by the device in figment_ack."""
    return hashlib.sha256(fig.canonical_json().encode("utf-8")).hexdigest()[:16]
