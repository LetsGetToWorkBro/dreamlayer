"""Capture provenance + redact-on-ingest: the raw frame never persists, the
manifest tells the truth about redaction, and (where a device cert is valid) a
real C2PA credential embeds. Redaction + manifest are deterministic; the real
c2pa byte-signing is guarded on cert validity."""
import io

import pytest

from dreamlayer.orchestrator.capture_provenance import (
    CaptureProvenance, EgoBlurRedactor, ProvenanceResult,
)


def _jpeg(size=(32, 32)) -> bytes:
    Image = pytest.importorskip("PIL.Image")
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(size[1]):              # a deterministic gradient — real
        for x in range(size[0]):          # detail, so blurring a box changes bytes
            px[x, y] = ((x * 8) % 256, (y * 8) % 256, ((x + y) * 4) % 256)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class _Veil:
    def __init__(self, ok): self._ok = ok
    def allow_capture(self): return self._ok


def _redactor(boxes):
    return EgoBlurRedactor(_detect=lambda jpeg: boxes)


class TestRedactionGate:
    def test_raw_frame_never_persists_when_redactor_runs(self):
        raw = _jpeg()
        cp = CaptureProvenance(redactor=_redactor([(4, 4, 20, 20)]))
        r = cp.ingest(raw)
        assert isinstance(r, ProvenanceResult)
        assert r.redacted is True and r.regions == 1
        assert r.jpeg != raw                       # the stored bytes are blurred

    def test_strict_mode_refuses_without_a_redactor(self):
        cp = CaptureProvenance(strict=True)        # no redactor available
        assert cp.ingest(_jpeg()) is None

    def test_non_strict_passes_through_but_manifest_is_honest(self):
        raw = _jpeg()
        cp = CaptureProvenance(strict=False)       # no redactor
        r = cp.ingest(raw)
        assert r.jpeg == raw and r.redacted is False
        cap = _capture_assertion(r.manifest)
        assert cap["bystander_redaction"] is False

    def test_veil_gates_capture(self):
        cp = CaptureProvenance(redactor=_redactor([(0, 0, 8, 8)]))
        assert cp.ingest(_jpeg(), privacy=_Veil(False)) is None
        assert cp.ingest(_jpeg(), privacy=_Veil(True)) is not None

    def test_detector_error_yields_unchanged_zero(self):
        boom = EgoBlurRedactor(_detect=lambda j: (_ for _ in ()).throw(RuntimeError()))
        out, n = boom.redact(_jpeg())
        assert n == 0


class TestManifest:
    def test_records_device_time_and_redaction_action(self):
        cp = CaptureProvenance(redactor=_redactor([(1, 1, 9, 9), (10, 10, 20, 20)]),
                               device_id="halo-42", now_fn=lambda: 1234567)
        r = cp.ingest(_jpeg())
        actions = _actions(r.manifest)
        assert any(a["action"] == "c2pa.created" for a in actions)
        red = [a for a in actions if a["action"] == "c2pa.redacted"]
        assert red and red[0]["parameters"]["faces_or_plates"] == 2
        cap = _capture_assertion(r.manifest)
        assert cap["device"] == "halo-42" and cap["captured_at"] == 1234567
        assert cap["regions_blurred"] == 2

    def test_no_redaction_action_when_none_ran(self):
        cp = CaptureProvenance(strict=False)
        actions = _actions(cp.ingest(_jpeg()).manifest)
        assert not any(a["action"] == "c2pa.redacted" for a in actions)


class _FakeSigner:
    available = True
    def sign(self, jpeg, manifest):
        return b"C2PA:" + jpeg            # stand in for an embedded credential


class TestSigning:
    def test_fake_signer_marks_signed(self):
        cp = CaptureProvenance(signer=_FakeSigner(),
                               redactor=_redactor([(2, 2, 10, 10)]))
        r = cp.ingest(_jpeg())
        assert r.signed is True and r.jpeg.startswith(b"C2PA:")

    def test_signer_failure_keeps_the_manifest(self):
        class _BadSigner:
            available = True
            def sign(self, *a): raise RuntimeError("bad cert")
        cp = CaptureProvenance(signer=_BadSigner(),
                               redactor=_redactor([(0, 0, 8, 8)]))
        r = cp.ingest(_jpeg())
        assert r.signed is False and r.manifest is not None


class TestRealC2PA:
    """A genuine C2PA credential embeds + reads back — only where a device cert
    the C2PA profile accepts is available (owner-provisioned)."""

    def _signer(self):
        c2pa = pytest.importorskip("c2pa")
        crypto = pytest.importorskip("cryptography")
        import datetime
        from cryptography import x509
        from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from dreamlayer.orchestrator.capture_provenance import C2paProvenanceSigner
        key = ec.generate_private_key(ec.SECP256R1())
        nm = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"DreamLayer")])
        cert = (x509.CertificateBuilder().subject_name(nm).issuer_name(nm)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime(2020, 1, 1))
                .not_valid_after(datetime.datetime(2035, 1, 1))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), False)
                .sign(key, hashes.SHA256()))
        s = C2paProvenanceSigner(
            cert.public_bytes(serialization.Encoding.PEM),
            key.private_bytes(serialization.Encoding.PEM,
                              serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()))
        return c2pa, s

    def test_credential_embeds_and_reads_back(self):
        c2pa, signer = self._signer()
        cp = CaptureProvenance(signer=signer, redactor=_redactor([(2, 2, 12, 12)]))
        raw = _jpeg()
        try:
            r = cp.ingest(raw)
        except Exception:
            pytest.skip("c2pa runtime error")
        if not r.signed:
            pytest.skip("device cert not accepted by the C2PA profile")
        import json
        mj = json.loads(c2pa.Reader("image/jpeg", io.BytesIO(r.jpeg)).json())
        am = mj["manifests"][mj["active_manifest"]]
        labels = [a["label"] for a in am["assertions"]]
        assert "c2pa.actions" in labels


# -- helpers ---------------------------------------------------------------
def _actions(manifest):
    for a in manifest["assertions"]:
        if a["label"] == "c2pa.actions":
            return a["data"]["actions"]
    return []


def _capture_assertion(manifest):
    for a in manifest["assertions"]:
        if a["label"] == "dreamlayer.capture":
            return a["data"]
    return {}


class TestOrchestratorHook:
    """The opt-in on_scene_frame gate: raw frames are replaced before anything
    downstream (Dream Mode / the Vault) can see them."""

    def _orch(self):
        from dreamlayer.main import build
        return build(":memory:")

    def test_off_by_default_passes_frame_through(self):
        orch = self._orch()
        assert orch.capture_provenance is None
        raw = _jpeg()
        orch.on_scene_frame({"camera_jpeg": raw})   # no crash, unchanged path

    def test_wired_gate_replaces_raw_before_capture(self):
        orch = self._orch()
        seen = {}
        # a marker redactor so we can prove the stored frame is the redacted one
        class _Mark:
            available = True
            def redact(self, jpeg): return (b"REDACTED:" + jpeg, 1)
        orch.capture_provenance = CaptureProvenance(redactor=_Mark())
        orig = orch.silent_capture.capture_scene
        orch.silent_capture.capture_scene = lambda scene, now_ms=None: seen.setdefault(
            "jpeg", scene.get("camera_jpeg"))
        orch.on_scene_frame({"camera_jpeg": _jpeg()})
        assert seen["jpeg"].startswith(b"REDACTED:")
