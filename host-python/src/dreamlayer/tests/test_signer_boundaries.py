"""Mutant-killer boundary suite for v2/signer.py (P2-13).

The session signer is the deploy gate's trust anchor: every kept Figment is
HMAC-SHA256-signed with a per-install key, and the deployer refuses anything
unsigned or tampered. test_rc2_vault.py exercises it through the vault flow;
nothing pinned the primitive itself — the exact algorithm, the key lifecycle,
the constant-time compare path, the failure modes. Mutation testing showed the
usual cost: a swapped digest, a broken key reload, or a verify that returns
True on exception would all have stayed green.

These tests pin each behavior a mutant could flip. signer.py joins the
mutation gate's `only_mutate` list with this suite as its killer set.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import stat

import pytest

from dreamlayer.reality_compiler.v2 import native
from dreamlayer.reality_compiler.v2.signer import (
    SessionSigner, SigningError, content_hash, KEY_FILE, KEY_BYTES,
)


@pytest.fixture
def fig():
    return native.timer_figment(30)


@pytest.fixture
def signer(tmp_path):
    return SessionSigner(tmp_path)


class TestKeyLifecycle:
    def test_key_is_created_on_first_use(self, tmp_path):
        SessionSigner(tmp_path)
        assert (tmp_path / KEY_FILE).exists()

    def test_key_is_32_random_bytes_hex_encoded(self, tmp_path):
        SessionSigner(tmp_path)
        key = bytes.fromhex((tmp_path / KEY_FILE).read_text().strip())
        assert len(key) == KEY_BYTES == 32         # 256-bit key, not fewer

    def test_key_file_is_owner_only(self, tmp_path):
        SessionSigner(tmp_path)
        mode = stat.S_IMODE(os.stat(tmp_path / KEY_FILE).st_mode)
        assert mode == 0o600                       # chmod applied, exactly 0600

    def test_existing_key_is_reloaded_not_replaced(self, tmp_path, fig):
        a = SessionSigner(tmp_path)
        sig = a.sign(fig)
        b = SessionSigner(tmp_path)                # same dir → same key
        assert b.sign(fig) == sig                  # reload path, not regenerate
        assert b.verify(fig, sig)

    def test_fresh_installs_have_distinct_keys(self, tmp_path, fig):
        a = SessionSigner(tmp_path / "a")
        b = SessionSigner(tmp_path / "b")
        assert a.sign(fig) != b.sign(fig)          # key actually feeds the mac

    def test_key_dir_is_created_if_missing(self, tmp_path):
        SessionSigner(tmp_path / "deep" / "nested")
        assert (tmp_path / "deep" / "nested" / KEY_FILE).exists()


class TestSignAndVerify:
    def test_signature_is_hmac_sha256_of_canonical_json(self, tmp_path, fig):
        s = SessionSigner(tmp_path)
        key = bytes.fromhex((tmp_path / KEY_FILE).read_text().strip())
        expected = hmac.new(key, fig.canonical_json().encode("utf-8"),
                            hashlib.sha256).hexdigest()
        assert s.sign(fig) == expected             # exact algorithm, no drift

    def test_round_trip(self, signer, fig):
        assert signer.verify(fig, signer.sign(fig)) is True

    def test_tampered_figment_fails(self, signer, fig):
        sig = signer.sign(fig)
        fig.name = fig.name + "-tampered"
        assert signer.verify(fig, sig) is False

    def test_wrong_signature_fails(self, signer, fig):
        good = signer.sign(fig)
        flipped = ("0" if good[0] != "0" else "1") + good[1:]
        assert signer.verify(fig, flipped) is False

    def test_empty_and_none_signature_fail(self, signer, fig):
        assert signer.verify(fig, "") is False
        assert signer.verify(fig, None) is False   # the `or ""` guard

    def test_verify_returns_false_when_signing_raises(self, signer):
        class Broken:
            id = "broken"
            def canonical_json(self):
                raise RuntimeError("no json for you")
        assert signer.verify(Broken(), "deadbeef") is False   # except → False


class TestVerifyOrRaise:
    def test_passes_silently_on_a_good_signature(self, signer, fig):
        signer.verify_or_raise(fig, signer.sign(fig))          # no raise

    def test_raises_signing_error_naming_the_figment(self, signer, fig):
        with pytest.raises(SigningError) as e:
            signer.verify_or_raise(fig, "not-a-signature")
        # the wearer sees WHICH figment and WHY, verbatim — this message is
        # wearer-facing UX, so its exact wording is pinned (an `in`-check
        # wouldn't do: a string-wrap mutant still CONTAINS the substring)
        assert str(e.value) == (
            f"figment {fig.id} failed signature verification — "
            "not signed by this install's session key")

    def test_signing_error_is_a_value_error(self):
        assert issubclass(SigningError, ValueError)


class TestContentHash:
    def test_sixteen_hex_chars(self, fig):
        h = content_hash(fig)
        assert len(h) == 16 and int(h, 16) >= 0    # truncated sha256 hexdigest

    def test_is_key_independent(self, tmp_path, fig):
        # two installs, one figment → same content hash (unlike signatures)
        assert content_hash(fig) == content_hash(fig)
        expected = hashlib.sha256(
            fig.canonical_json().encode("utf-8")).hexdigest()[:16]
        assert content_hash(fig) == expected

    def test_tracks_content(self, fig):
        before = content_hash(fig)
        fig.name = fig.name + "!"
        assert content_hash(fig) != before
