"""Hardened secret store — the Brain's root-of-trust keys off cleartext (B5).

The Ed25519 receipt seed anchors the tamper-evident privacy ledger, yet every
root secret lived as a plaintext file readable by any process running as the
user, any backup, any sync client (refute 2026-07-18). secret_store puts them
behind a pluggable backend: a platform enclave/TPM plug, the OS keychain, or —
as the deliberate last resort — an owner-only file. These pin the contract:
priority order, read-through so an existing on-disk key survives the keychain
upgrade, backward-compatible file path/format, and the enclave seam.
"""
from __future__ import annotations

import os
import stat

import pytest

from dreamlayer.secret_store import (
    HardenedFileBackend, SecretBackend, SecretStore,
    register_secret_backend, _reset_enclave_backends,
)


@pytest.fixture(autouse=True)
def _clean_enclave():
    _reset_enclave_backends()
    yield
    _reset_enclave_backends()


# --- the file backend (always available) -------------------------------------

def test_file_backend_round_trips_and_is_owner_only(tmp_path):
    be = HardenedFileBackend(tmp_path)
    assert be.get("receipt") is None
    secret = os.urandom(32)
    be.set("receipt", secret)
    assert be.get("receipt") == secret
    p = tmp_path / "receipt.key"
    assert p.exists()
    if os.name == "posix":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_file_backend_uses_the_legacy_receipt_key_path(tmp_path):
    """Backward compat: the on-disk name/format is exactly what pre-B5 installs
    wrote, so an existing receipt.key is honoured, not orphaned."""
    p = tmp_path / "receipt.key"
    legacy = os.urandom(32)
    p.write_text(legacy.hex())
    assert HardenedFileBackend(tmp_path).get("receipt") == legacy


def test_file_backend_tolerates_corrupt_file(tmp_path):
    (tmp_path / "x.key").write_text("not hex ~~~")
    assert HardenedFileBackend(tmp_path).get("x") is None


def test_file_backend_delete(tmp_path):
    be = HardenedFileBackend(tmp_path)
    be.set("k", b"\x01" * 32)
    be.delete("k")
    assert be.get("k") is None


# --- the store: priority + get_or_create -------------------------------------

def test_get_or_create_mints_once_and_is_stable(tmp_path):
    store = SecretStore(tmp_path, prefer_keyring=False)
    a = store.get_or_create("receipt")
    b = store.get_or_create("receipt")
    assert a == b and len(a) == 32
    # a brand-new store over the same dir reads the same persisted secret
    assert SecretStore(tmp_path, prefer_keyring=False).get("receipt") == a


def test_get_or_create_honours_a_preexisting_file(tmp_path):
    legacy = os.urandom(32)
    (tmp_path / "receipt.key").write_text(legacy.hex())
    store = SecretStore(tmp_path, prefer_keyring=False)
    assert store.get_or_create("receipt") == legacy      # never re-minted


class _MemBackend(SecretBackend):
    """An in-memory stand-in for an enclave/keychain — highest priority."""
    kind = "mem"
    available = True

    def __init__(self):
        self._d = {}

    def get(self, name):
        return self._d.get(name)

    def set(self, name, value):
        self._d[name] = value

    def delete(self, name):
        self._d.pop(name, None)


def test_enclave_backend_takes_priority_for_new_secrets(tmp_path):
    mem = _MemBackend()
    register_secret_backend(mem)
    store = SecretStore(tmp_path, prefer_keyring=False)
    secret = store.get_or_create("receipt")
    # minted into the enclave, NOT the file
    assert mem.get("receipt") == secret
    assert not (tmp_path / "receipt.key").exists()


def test_existing_file_key_survives_when_an_enclave_appears(tmp_path):
    """The upgrade path: a key already on disk must stay authoritative once a
    higher-trust backend is registered — else the receipt public key would change
    and every past receipt would break."""
    legacy = os.urandom(32)
    (tmp_path / "receipt.key").write_text(legacy.hex())
    register_secret_backend(_MemBackend())               # empty enclave appears
    store = SecretStore(tmp_path, prefer_keyring=False)
    assert store.get_or_create("receipt") == legacy      # read-through wins


def test_set_writes_to_highest_priority_and_get_reads_through(tmp_path):
    mem = _MemBackend()
    register_secret_backend(mem)
    store = SecretStore(tmp_path, prefer_keyring=False)
    store.set("k", b"\x02" * 32)
    assert mem.get("k") == b"\x02" * 32
    assert store.get("k") == b"\x02" * 32


def test_backends_order_is_enclave_then_file(tmp_path):
    register_secret_backend(_MemBackend())
    store = SecretStore(tmp_path, prefer_keyring=False)
    kinds = [b.kind for b in store.backends]
    assert kinds[0] == "mem" and kinds[-1] == "file"


# --- keyring probe is fail-safe ----------------------------------------------

def test_keyring_backend_probe_is_fail_safe():
    """Constructing the keyring backend never raises, whether or not keyring is
    installed; when it resolves to a null/fail store it reports unavailable."""
    from dreamlayer.secret_store import KeyringBackend
    be = KeyringBackend()
    assert isinstance(be.available, bool)
    if not be.available:
        assert be.get("anything") is None


# --- the receipt signer now flows through the store --------------------------

def test_receipt_signer_uses_the_store_and_stays_stable(tmp_path):
    pytest.importorskip("cryptography")
    from dreamlayer.ai_brain.server.store import activity_receipt_signer
    s1 = activity_receipt_signer(tmp_path)
    s2 = activity_receipt_signer(tmp_path)
    assert s1 is not None
    assert s1.public_key_hex == s2.public_key_hex        # one persisted seed
    # stored under the backward-compatible path
    assert (tmp_path / "receipt.key").exists()
