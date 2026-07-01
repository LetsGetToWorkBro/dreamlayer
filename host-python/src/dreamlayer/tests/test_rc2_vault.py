"""Signing, vault storage, revocation durability, explicit export."""
import json

import pytest

from dreamlayer.reality_compiler.v2 import (
    Figment, Scene, TextLine, Transition, END,
    Vault, SessionSigner, SigningError, content_hash,
)


@pytest.fixture
def fig() -> Figment:
    f = Figment(name="Timer", initial="a")
    f.add_scene(Scene(id="a", duration_sec=10.0,
                      lines=[TextLine("hi", row=1)],
                      on_timeout=[Transition(target=END)]))
    return f


@pytest.fixture
def vault(tmp_path) -> Vault:
    return Vault(tmp_path / "vault")


class TestSigner:
    def test_sign_verify_roundtrip(self, tmp_path, fig):
        s = SessionSigner(tmp_path)
        sig = s.sign(fig)
        assert s.verify(fig, sig)

    def test_key_persists(self, tmp_path, fig):
        sig = SessionSigner(tmp_path).sign(fig)
        assert SessionSigner(tmp_path).verify(fig, sig)

    def test_key_file_is_private(self, tmp_path, fig):
        SessionSigner(tmp_path).sign(fig)
        assert (tmp_path / "session.key").stat().st_mode & 0o077 == 0

    def test_other_install_cannot_forge(self, tmp_path, fig):
        sig = SessionSigner(tmp_path / "phone_a").sign(fig)
        assert not SessionSigner(tmp_path / "phone_b").verify(fig, sig)

    def test_tampered_content_fails(self, tmp_path, fig):
        s = SessionSigner(tmp_path)
        sig = s.sign(fig)
        fig.scenes["a"].duration_sec = 9999.0
        assert not s.verify(fig, sig)

    def test_content_hash_stable(self, fig):
        assert content_hash(fig) == content_hash(fig)


class TestVault:
    def test_keep_load_roundtrip(self, vault, fig):
        vault.keep(fig)
        entry = vault.load(fig.id)
        assert entry.figment.canonical_json() == fig.canonical_json()
        assert entry.active

    def test_tampered_file_never_surfaces(self, vault, fig):
        vault.keep(fig)
        path = vault._path(fig.id)
        raw = json.loads(path.read_text())
        raw["figment"]["scenes"]["a"]["duration_sec"] = 86400.0
        path.write_text(json.dumps(raw))
        with pytest.raises(SigningError):
            vault.load(fig.id)
        assert vault.list() == []            # silently excluded from listing

    def test_revocation_is_durable(self, vault, fig):
        vault.keep(fig)
        vault.revoke(fig.id)
        assert vault.load(fig.id).revoked
        # a re-kept file with the same id stays revoked
        vault.keep(fig)
        assert vault.is_revoked(fig.id)

    def test_list_hides_revoked_by_default(self, vault, fig):
        vault.keep(fig)
        vault.revoke(fig.id)
        assert vault.list() == []
        assert len(vault.list(include_revoked=True)) == 1

    def test_export_is_explicit_and_signed(self, vault, fig, tmp_path):
        vault.keep(fig)
        out = vault.export(fig.id, tmp_path / "out.json")
        payload = json.loads(out.read_text())
        assert payload["figment"]["id"] == fig.id
        assert payload["sig"]

    def test_revoked_not_exportable(self, vault, fig, tmp_path):
        vault.keep(fig)
        vault.revoke(fig.id)
        with pytest.raises(SigningError, match="revoked"):
            vault.export(fig.id, tmp_path / "out.json")

    def test_performance_history(self, vault, fig):
        vault.keep(fig)
        vault.record_performance(fig.id, {"place": "gym"})
        vault.record_performance(fig.id, {"place": "gym"})
        hist = vault.performance_history(fig.id)
        assert len(hist) == 2 and hist[0]["place"] == "gym"
