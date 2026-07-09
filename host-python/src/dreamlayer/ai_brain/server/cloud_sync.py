"""cloud_sync.py — the client half of DreamLayer Cloud sync (docs/CLOUD.md).

The Brain already has a full snapshot pair — export_backup()/import_backup(),
deliberately localhost-only because the export includes secrets. Cloud sync
lifts that snapshot off the device under two hard rules this module enforces:

  1. SECRETS NEVER SYNC. The pairing token and any cloud API key are stripped
     before the blob leaves this function. Each device keeps its own.
  2. THE SERVER STORES CIPHERTEXT ONLY. The blob is encrypted client-side
     (Fernet, via the optional `cryptography` dependency — the Guardian pack /
     `privacy` extra) with a key derived from a passphrase only the user
     holds. No cryptography installed → we refuse loudly. Plaintext sync is
     not a fallback; it would break the product's core promise.

The upload/download halves live server-side (R2 behind api.dreamlayer.app,
phase P2 in docs/CLOUD.md); this module produces and opens the blobs, so the
transport can be dumb and blind.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Optional

log = logging.getLogger("dreamlayer.cloud_sync")

try:
    from cryptography.fernet import Fernet, InvalidToken  # type: ignore
    _HAS_FERNET = True
except BaseException:            # ImportError, or a broken native install
    _HAS_FERNET = False

available = _HAS_FERNET

# Config fields that must never leave the device. Kept explicit and tested —
# a new secret field should be added here the day it is added to BrainConfig.
SECRET_FIELDS = ("token", "cloud_api_key")


class SyncUnavailable(RuntimeError):
    """Raised when encrypted sync can't be provided (no cryptography lib)."""


def _key_from_passphrase(passphrase: str) -> bytes:
    """Deterministic Fernet key from the user's passphrase. scrypt keeps a
    weak passphrase expensive to grind; the salt is fixed app-wide because the
    passphrase is per-user and the blob format needs to be openable on a brand
    new device with nothing but the passphrase."""
    raw = hashlib.scrypt(passphrase.encode(), salt=b"dreamlayer-sync-v1",
                         n=2**14, r=8, p=1, dklen=32)
    return base64.urlsafe_b64encode(raw)


def strip_secrets(snapshot: dict) -> dict:
    """A copy of a backup snapshot with device-local secrets removed."""
    out = json.loads(json.dumps(snapshot))          # deep copy, JSON-safe
    cfg = out.get("config")
    if isinstance(cfg, dict):
        for field in SECRET_FIELDS:
            cfg.pop(field, None)
    return out


def prepare_sync_blob(brain, passphrase: str) -> bytes:
    """export_backup() → strip secrets → encrypt. The bytes returned are safe
    to hand to any storage — the server never sees plaintext or secrets."""
    if not _HAS_FERNET:
        raise SyncUnavailable(
            "encrypted sync needs the 'cryptography' package "
            "(pip install \"dreamlayer[privacy]\") — plaintext sync is not offered")
    if not passphrase or len(passphrase) < 8:
        raise ValueError("sync passphrase must be at least 8 characters")
    snapshot = strip_secrets(brain.export_backup())
    payload = json.dumps({"v": 1, "snapshot": snapshot}).encode()
    return Fernet(_key_from_passphrase(passphrase)).encrypt(payload)


def open_sync_blob(blob: bytes, passphrase: str) -> Optional[dict]:
    """Decrypt + parse a sync blob. Returns the snapshot dict (secrets absent
    by construction), or None if the passphrase is wrong / blob is corrupt —
    a caller shows 'wrong passphrase', never a stack trace."""
    if not _HAS_FERNET:
        raise SyncUnavailable(
            "encrypted sync needs the 'cryptography' package "
            "(pip install \"dreamlayer[privacy]\")")
    try:
        payload = Fernet(_key_from_passphrase(passphrase)).decrypt(blob)
        data = json.loads(payload.decode())
    except (InvalidToken, ValueError, KeyError):
        return None
    if data.get("v") != 1:
        return None
    return data.get("snapshot")
