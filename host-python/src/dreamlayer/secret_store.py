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
import tempfile
from pathlib import Path
from typing import Any, Callable, List, Optional

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
        self._harden_dir(p.parent)
        # mkstemp opens O_CREAT|O_EXCL at 0o600, so the secret is NEVER on disk
        # world-readable — the previous write_text-then-chmod left a 0o644 window
        # (and a 0o644 leftover on a crash), the exact flaw the config path already
        # fixed with mkstemp (refute 2026-07-18).
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(value.hex())
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        self._harden_windows(str(p))                  # 0o600 is inert on NTFS

    def _harden_dir(self, d: Path) -> None:
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)                         # owner-only dir on first boot
        except OSError:
            pass
        self._harden_windows(str(d))

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
        self._keyring: Any = None
        self.available = self._probe()

    _PROBE_NAME = "__dreamlayer_probe__"

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
        if isinstance(active, _fail.Keyring):
            return False
        # FUNCTIONAL round-trip, not just a class check: a real keychain that is
        # LOCKED, a Secret Service with no DBus session, or the null backend all
        # report a plausible class but silently drop on use. If we trusted the
        # class we'd mint a new secret into a black hole and lose the old one —
        # so a locked/nonfunctional keyring must report UNAVAILABLE, letting the
        # store fall back to the durable file (refute 2026-07-18). (This also
        # replaces the old "fail"/"null" substring guard, which wrongly disabled
        # legitimate backends whose module path happened to contain those words.)
        try:
            keyring.set_password(self._service, self._PROBE_NAME, "1")
            ok = keyring.get_password(self._service, self._PROBE_NAME) == "1"
            try:
                keyring.delete_password(self._service, self._PROBE_NAME)
            except Exception:
                pass
        except Exception:
            return False
        if not ok:
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
        # Each backend read is guarded: a platform enclave that raises (a flaky
        # TPM plug) must be SKIPPED, never crash server startup — the file backend
        # always answers last (refute 2026-07-18: get() was unguarded).
        for b in self._backends:
            if not getattr(b, "available", False):
                continue
            try:
                val = b.get(name)
            except Exception as exc:
                log.warning("[secret_store] %s get failed: %s", getattr(b, "kind", "?"), exc)
                continue
            if val:
                return val
        return None

    def set(self, name: str, value: bytes) -> None:
        """Write to the highest-priority backend that accepts it, cascading down
        on error. The file backend is always available and last, so set() cannot
        fail on a locked keychain / read-only enclave — it just lands one tier
        lower (refute 2026-07-18: set() was a bare _preferred().set that crashed)."""
        last_exc: Optional[Exception] = None
        for b in self._backends:
            if not getattr(b, "available", False):
                continue
            try:
                b.set(name, value)
                return
            except Exception as exc:
                last_exc = exc
                log.warning("[secret_store] %s set failed: %s; trying next backend",
                            getattr(b, "kind", "?"), exc)
        if last_exc is not None:
            raise last_exc

    def delete(self, name: str) -> None:
        for b in self._backends:
            if getattr(b, "available", False):
                try:
                    b.delete(name)
                except Exception as exc:
                    log.warning("[secret_store] %s delete failed: %s",
                                getattr(b, "kind", "?"), exc)

    def get_or_create(self, name: str,
                      factory: Callable[[], bytes] = lambda: os.urandom(32)) -> bytes:
        """Return the secret, minting one only if NO backend already holds it.

        Reading through every backend first keeps a pre-existing key authoritative
        after a higher backend arrives — the receipt public key stays stable, so
        every past receipt still verifies. On a mint, set() cascades to a durable
        backend (never crashes on a locked keychain); then we RE-READ so two
        concurrent first-boot processes converge on the persisted winner rather
        than each returning its own key (refute 2026-07-18)."""
        existing = self.get(name)
        if existing:
            return existing
        value = factory()
        self.set(name, value)                          # cascades; file is the backstop
        return self.get(name) or value                 # converge on the stored winner


def secret_store(cfg_dir: Path | str, **kw) -> SecretStore:
    """Factory mirroring the other *_store helpers."""
    return SecretStore(cfg_dir, **kw)
