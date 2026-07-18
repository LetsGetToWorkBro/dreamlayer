"""secret_store.py — where the Brain's secrets actually live.

The Brain holds several root-of-trust secrets: the TLS private key, the
Ed25519 receipt-signing seed (the anchor of the tamper-evident privacy ledger),
the pairing token, and cloud API keys. Every one of them was a plaintext file —
0o600 at best, but still bytes on disk that any process running as the user, any
backup, any sync client, or anyone with the powered-off disk can read. On a
device that promises "your life stays yours", the signing seed sitting in
cleartext next to the ledger it protects is the weakest link.

This is the one place a secret is stored, behind a pluggable backend so the
storage can get *stronger* without touching a single caller:

  * EnclaveBackend  — a native Secure Enclave / TPM / StrongBox backend, injected
    by the platform layer via register_secret_backend(). The seam is here and
    load-bearing today; the native implementation ships with the signed platform
    app (it needs code the OS will trust), so this module treats it as an
    optional, highest-priority plug rather than pretending to be an enclave.
  * KeyringBackend  — the OS keychain (macOS Keychain, Windows Credential Locker,
    Linux Secret Service) via the `keyring` extra. Secrets leave the filesystem
    entirely and inherit the OS's at-rest protection and access control.
  * HardenedFileBackend — the always-available fallback: owner-only file
    (chmod 0o600 + the same Windows owner-only ACL the state dir uses). Same
    bytes-on-disk exposure as before, but now the deliberate last resort, not the
    only option.

get_or_create() reads through ALL backends before minting a new secret, so an
existing on-disk key is honoured even after the keychain becomes available — the
receipt public key (and therefore every past receipt) stays valid across the
upgrade. Fail-safe: a backend that errors is skipped, never fatal; the file
backend always answers.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, List, Optional

log = logging.getLogger("dreamlayer.secret_store")

DEFAULT_SERVICE = "dreamlayer"

# Platform-injected high-trust backends (Secure Enclave / TPM). Empty by default;
# the signed platform app calls register_secret_backend() at startup.
_ENCLAVE_BACKENDS: List["SecretBackend"] = []


class SecretBackend:
    """Interface: get/set/delete a named secret as raw bytes. `kind` names the
    backend for logging; `available` gates whether it is consulted."""
    kind = "abstract"
    available = False

    def get(self, name: str) -> Optional[bytes]:      # pragma: no cover - abstract
        raise NotImplementedError

    def set(self, name: str, value: bytes) -> None:   # pragma: no cover - abstract
        raise NotImplementedError

    def delete(self, name: str) -> None:              # pragma: no cover - abstract
        raise NotImplementedError


def register_secret_backend(backend: SecretBackend) -> None:
    """Install a platform enclave/TPM backend at the highest priority. Idempotent
    per instance; the most recently registered wins first look."""
    if backend not in _ENCLAVE_BACKENDS:
        _ENCLAVE_BACKENDS.insert(0, backend)


def _reset_enclave_backends() -> None:
    """Test hook: drop any registered enclave backends."""
    _ENCLAVE_BACKENDS.clear()


class HardenedFileBackend(SecretBackend):
    """Owner-only file per secret: ``<dir>/<name>.key``, hex-encoded, chmod 0o600
    plus the Windows owner-only ACL. The always-available fallback and the
    on-disk format existing installs already use (so keys migrate transparently)."""
    kind = "file"
    available = True

    def __init__(self, directory: Path | str):
        self._dir = Path(directory)

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.key"

    def get(self, name: str) -> Optional[bytes]:
        p = self._path(name)
        try:
            if not p.exists():
                return None
            raw = bytes.fromhex(p.read_text().strip())
            return raw or None
        except (OSError, ValueError):
            return None

    def set(self, name: str, value: bytes) -> None:
        p = self._path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(value.hex())
        try:
            os.chmod(tmp, 0o600)                       # secret-at-rest: owner only
        except OSError:
            pass
        os.replace(tmp, p)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        self._harden_windows(str(p))                  # 0o600 is inert on NTFS

    def delete(self, name: str) -> None:
        try:
            self._path(name).unlink()
        except OSError:
            pass

    @staticmethod
    def _harden_windows(path: str) -> None:
        try:
            from .ai_brain.server.store import _harden_windows_acl
            _harden_windows_acl(path)
        except Exception as exc:                      # pragma: no cover - defensive
            log.debug("[secret_store] windows ACL hardening skipped: %s", exc)


class KeyringBackend(SecretBackend):
    """OS keychain via the `keyring` extra. Secrets leave the filesystem for the
    platform credential store. ``available`` is False when keyring isn't installed
    or resolves to its null/fail backend (no real store present)."""
    kind = "keyring"

    def __init__(self, service: str = DEFAULT_SERVICE):
        self._service = service
        self._keyring = None
        self.available = self._probe()

    def _probe(self) -> bool:
        try:
            import keyring  # type: ignore
            from keyring.backends import fail as _fail  # type: ignore
        except Exception:
            return False
        try:
            active = keyring.get_keyring()
        except Exception:
            return False
        # A null/fail backend "works" but stores nothing — treat as unavailable so
        # we don't silently drop secrets into a black hole instead of the file.
        cls_path = f"{type(active).__module__}.{type(active).__name__}".lower()
        if isinstance(active, _fail.Keyring) or "null" in cls_path or "fail" in cls_path:
            return False
        self._keyring = keyring
        return True

    def get(self, name: str) -> Optional[bytes]:
        if not self.available:
            return None
        try:
            hexval = self._keyring.get_password(self._service, name)
            return bytes.fromhex(hexval) if hexval else None
        except Exception as exc:                       # keychain locked / IO error
            log.debug("[secret_store] keyring get failed for %s: %s", name, exc)
            return None

    def set(self, name: str, value: bytes) -> None:
        if not self.available:
            raise RuntimeError("keyring backend unavailable")
        self._keyring.set_password(self._service, name, value.hex())

    def delete(self, name: str) -> None:
        if not self.available:
            return
        try:
            self._keyring.delete_password(self._service, name)
        except Exception:
            pass


class SecretStore:
    """The Brain's secret store: enclave > keychain > owner-only file, consulted
    in that order. Callers name a secret; the store decides where it safely lives.

    Parameters
    ----------
    file_dir : the directory for the hardened-file fallback (the Brain cfg dir).
    service  : keychain service namespace.
    prefer_keyring : set False to force the file backend (tests / headless).
    """

    def __init__(self, file_dir: Path | str, *, service: str = DEFAULT_SERVICE,
                 prefer_keyring: bool = True):
        self._file = HardenedFileBackend(file_dir)
        self._keyring = KeyringBackend(service) if prefer_keyring else None
        # priority: platform enclave(s) → OS keychain → owner-only file
        chain: List[SecretBackend] = list(_ENCLAVE_BACKENDS)
        if self._keyring is not None and self._keyring.available:
            chain.append(self._keyring)
        chain.append(self._file)
        self._backends = chain

    @property
    def backends(self) -> List[SecretBackend]:
        return list(self._backends)

    def _preferred(self) -> SecretBackend:
        """The highest-priority backend that can actually store (skip read-only
        enclaves that don't implement set)."""
        for b in self._backends:
            if getattr(b, "available", False):
                return b
        return self._file

    def get(self, name: str) -> Optional[bytes]:
        for b in self._backends:
            if not getattr(b, "available", False):
                continue
            val = b.get(name)
            if val:
                return val
        return None

    def set(self, name: str, value: bytes) -> None:
        self._preferred().set(name, value)

    def delete(self, name: str) -> None:
        for b in self._backends:
            if getattr(b, "available", False):
                b.delete(name)

    def get_or_create(self, name: str,
                      factory: Callable[[], bytes] = lambda: os.urandom(32)) -> bytes:
        """Return the secret, minting one only if NO backend already holds it.

        Reading through every backend first is what keeps a pre-existing on-disk
        key authoritative after the keychain arrives — the receipt public key
        stays stable, so every past receipt still verifies. A freshly minted
        secret goes to the strongest available backend."""
        existing = self.get(name)
        if existing:
            return existing
        value = factory()
        try:
            self._preferred().set(name, value)
        except Exception as exc:                       # keychain locked mid-create
            log.warning("[secret_store] preferred backend store failed (%s); "
                        "falling back to owner-only file", exc)
            self._file.set(name, value)
        return value


def secret_store(cfg_dir: Path | str, **kw) -> SecretStore:
    """Factory mirroring the other *_store helpers."""
    return SecretStore(cfg_dir, **kw)
