"""Author signing — defence 2b of the plugin gate, plus the figment
sharing gate. Integrity (sha256) says the bytes are intact; authenticity
(Ed25519) says who produced them. Unsigned stays installable under the
curated-registry model; an INVALID signature is always a hard refusal."""
import pytest

from dreamlayer.plugins.package import PluginPackage
from dreamlayer.plugins.validate import validate
from dreamlayer.reality_compiler import sign_crypto
from dreamlayer.reality_compiler.sign_crypto import Signer, verify_detached

HAS_CRYPTO = sign_crypto._HAS_CRYPTO

SOURCE = '''
from dreamlayer.plugins.base import make_plugin

def make():
    def register(ctx):
        pass
    return make_plugin("hello", register)
'''


def build(**kw):
    return PluginPackage.build(
        name="hello-signed", version="0.1.0", entry="plugin:make",
        source=SOURCE, author="tester", **kw)


class TestVerifyDetached:
    @pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography not installed")
    def test_roundtrip(self):
        s = Signer(b"\x07" * 32)
        sig = s.sign(b"payload")
        assert verify_detached(b"payload", sig, s.public_key_hex) is True
        assert verify_detached(b"tampered", sig, s.public_key_hex) is False

    def test_unverifiable_without_crypto(self, monkeypatch):
        monkeypatch.setattr(sign_crypto, "_HAS_CRYPTO", False)
        assert verify_detached(b"x", "00" * 64, "11" * 32) is None


class TestPluginGateAuthenticity:
    def test_unsigned_is_warning_not_refusal(self):
        report = validate(build(), host_capabilities=frozenset())
        assert report.ok
        assert report.signed is False
        assert any("unsigned" in w for w in report.warnings)

    @pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography not installed")
    def test_signed_package_verifies(self):
        pkg = build().sign_with(Signer(b"\x21" * 32))
        report = validate(pkg, host_capabilities=frozenset())
        assert report.ok and report.signed is True

    @pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography not installed")
    def test_tampered_code_fails_hard(self):
        pkg = build().sign_with(Signer(b"\x21" * 32))
        pkg.source += "\n# evil\n"
        # keep the checksum consistent with the tampered code so ONLY the
        # signature catches it (the re-sign-after-tamper attack)
        from dreamlayer.plugins.package import sha256_of
        pkg.manifest.checksum = sha256_of(pkg.source)
        report = validate(pkg, host_capabilities=frozenset())
        assert not report.ok
        assert any("INVALID" in e for e in report.errors)

    @pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography not installed")
    def test_widened_requires_fails_hard(self):
        # the whole point of signing the manifest, not just the code: an
        # attacker who takes a signed package and widens its capabilities
        # invalidates the signature.
        pkg = build().sign_with(Signer(b"\x21" * 32))
        pkg.manifest.requires = ("network", "fs")
        report = validate(pkg, host_capabilities=frozenset({"network", "fs"}))
        assert not report.ok and any("INVALID" in e for e in report.errors)

    @pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography not installed")
    def test_redirected_entry_fails_hard(self):
        pkg = build().sign_with(Signer(b"\x21" * 32))
        pkg.manifest.entry = "plugin:evil"      # redirect the load target
        report = validate(pkg, host_capabilities=frozenset())
        assert not report.ok and any("INVALID" in e for e in report.errors)

    @pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography not installed")
    def test_trusted_registry_rejects_unknown_key(self):
        pkg = build().sign_with(Signer(b"\x21" * 32))
        other = Signer(b"\x42" * 32)
        report = validate(pkg, host_capabilities=frozenset(),
                          trusted_keys={"someone-else": other.public_key_hex})
        assert not report.ok
        assert any("trusted publisher registry" in e for e in report.errors)

    @pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography not installed")
    def test_trusted_registry_names_publisher(self):
        s = Signer(b"\x21" * 32)
        pkg = build().sign_with(s)
        report = validate(pkg, host_capabilities=frozenset(),
                          trusted_keys={"tester": s.public_key_hex})
        assert report.ok and report.publisher == "tester"

    def test_signature_without_pubkey_refused(self):
        pkg = build(signature="ab" * 32)
        report = validate(pkg, host_capabilities=frozenset())
        assert not report.ok

    def test_signature_unverifiable_without_crypto_is_unsigned(self, monkeypatch):
        pkg = build(signature="ab" * 32)
        pkg.manifest.pubkey = "cd" * 32
        monkeypatch.setattr(sign_crypto, "_HAS_CRYPTO", False)
        report = validate(pkg, host_capabilities=frozenset())
        assert report.ok            # curated model still applies…
        assert report.signed is False   # …but the claim earns nothing
        assert any("NOT verified" in w for w in report.warnings)

    def test_hmac_fallback_signer_cannot_publish(self, monkeypatch):
        monkeypatch.setattr(sign_crypto, "_HAS_CRYPTO", False)
        s = sign_crypto.Signer(b"\x21" * 32)
        s._pub = None               # what a crypto-less env produces
        with pytest.raises(ValueError):
            build().sign_with(s)


class TestFigmentSharingGate:
    def _kept_figment(self, tmp_path, require_author_sig, origin=None):
        from dreamlayer.reality_compiler.v2 import RealityCompilerV2
        rc = RealityCompilerV2(vault_dir=tmp_path / "vault")
        s = rc.rehearse("Rolling")
        s.double_tap()
        s.say("rolling - three minutes")
        fig = s.finish().figment
        if origin:
            fig.meta["origin"] = origin
        rc.keep(fig)
        rc.deployer.require_author_sig = require_author_sig
        return rc, fig

    def test_self_authored_deploys_without_author_sig(self, tmp_path):
        rc, fig = self._kept_figment(tmp_path, require_author_sig=True)
        assert rc.deploy(fig.id).success

    def test_shared_without_author_sig_refused(self, tmp_path):
        rc, fig = self._kept_figment(tmp_path, require_author_sig=True,
                                     origin="shared")
        rec = rc.deploy(fig.id)
        assert not rec.success and "author signature" in rec.message

    @pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography not installed")
    def test_shared_with_valid_author_sig_deploys(self, tmp_path):
        rc, fig = self._kept_figment(tmp_path, require_author_sig=True,
                                     origin="shared")
        author = Signer(b"\x33" * 32)
        body = fig.to_dict()
        body["meta"] = {k: v for k, v in (body.get("meta") or {}).items()
                        if k not in ("author_sig", "author_pubkey")}
        fig.meta["author_sig"] = author.sign(body)
        fig.meta["author_pubkey"] = author.public_key_hex
        rc.keep(fig)                       # re-sign the vault entry
        assert rc.deploy(fig.id).success
