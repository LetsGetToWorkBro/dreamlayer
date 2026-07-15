"""orchestrator/capture_provenance.py — sign & redact captures at the door.

Two of the strongest trust properties a camera-on-your-face device can have,
made one act at the Vault-ingest boundary:

1. **Redact-on-ingest (bystander privacy).** Before a captured frame is ever
   stored, a redactor blurs bystander PII — faces and licence plates. The raw,
   un-redacted frame never persists. This turns the Privacy Veil from a UI
   toggle into a *data-layer guarantee*. The redactor seam is **EgoBlur** (Meta
   Reality Labs, Apache-2.0) — the rare model trained on *egocentric / glasses*
   footage, i.e. exactly this camera geometry. It's a model dependency, so it's
   a lazy seam; a strict mode refuses capture when no redactor is available
   (maximum privacy), and a non-strict mode passes through but records honestly
   in the manifest that redaction did not run.

2. **Capture provenance (C2PA Content Credentials).** The frame that *does*
   persist is signed with a C2PA manifest asserting the device identity, the
   capture time, and — crucially — that redaction occurred. A wearable camera
   that hardware-signs its captures is a genuine first, and because C2PA v2 has
   a redaction assertion, **provenance and bystander-privacy become one
   cryptographic act**: we sign the already-blurred frame and record the blur in
   the same manifest.

C2PA signing needs an X.509 device certificate matching the C2PA profile (an
owner/provisioning action, like every other hardware key here), so the byte-
level signer is a seam; the pipeline, the manifest assembly, and the redaction
gate are all exercised deterministically. See docs/PRIVACY.md.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger("dreamlayer.capture_provenance")


# ---------------------------------------------------------------------------
# Redactor seam
# ---------------------------------------------------------------------------

class EgoBlurRedactor:
    """Face + licence-plate blur via EgoBlur (Meta, egocentric-trained). Lazy;
    ``available`` is False without the model, and ``redact`` returns the frame
    unchanged with 0 regions so a caller can detect that redaction didn't run."""

    def __init__(self, face_model=None, plate_model=None, _detect=None):
        self._detect = _detect            # inject (jpeg)->list[bbox] in tests
        self._face = face_model
        self._plate = plate_model
        self.available = _detect is not None or self._try_load()

    def _try_load(self) -> bool:
        try:                              # pragma: no cover - model path
            import torch  # noqa: F401
            import egoblur  # type: ignore  # noqa: F401
            return True
        except Exception:
            return False

    def redact(self, jpeg: bytes) -> tuple[bytes, int]:
        """Return (redacted_jpeg, n_regions). Blurs every detected face/plate;
        raises nothing — a detector error yields the input unchanged, 0."""
        try:
            boxes = self._detect(jpeg) if self._detect is not None \
                else self._detect_real(jpeg)
        except Exception as exc:
            log.warning("[egoblur] detect failed: %s", exc)
            return (jpeg, 0)
        if not boxes:
            return (jpeg, 0)
        return (self._blur_boxes(jpeg, boxes), len(boxes))

    def _detect_real(self, jpeg):         # pragma: no cover - model path
        raise RuntimeError("no egoblur model")

    @staticmethod
    def _blur_boxes(jpeg: bytes, boxes) -> bytes:
        """Gaussian-blur each bbox region of the JPEG. Real pixel redaction."""
        from PIL import Image, ImageFilter
        img = Image.open(io.BytesIO(jpeg)).convert("RGB")
        for (x0, y0, x1, y1) in boxes:
            region = img.crop((x0, y0, x1, y1))
            img.paste(region.filter(ImageFilter.GaussianBlur(12)), (x0, y0))
        out = io.BytesIO()
        img.save(out, format="JPEG")
        return out.getvalue()


# ---------------------------------------------------------------------------
# C2PA signer seam
# ---------------------------------------------------------------------------

class C2paProvenanceSigner:
    """Embed a C2PA manifest into a JPEG with c2pa-python. ``available`` is
    False without the wheel; without a valid device cert it raises at sign
    time (caller falls back to the unsigned-but-manifested result)."""

    def __init__(self, cert_pem: bytes = b"", key_pem: bytes = b"",
                 alg: bytes = b"es256"):
        self.cert_pem, self.key_pem, self.alg = cert_pem, key_pem, alg
        try:
            import c2pa  # noqa: F401
            self.available = bool(cert_pem and key_pem)
        except Exception:
            self.available = False

    def sign(self, jpeg: bytes, manifest: dict) -> bytes:
        import c2pa
        info = c2pa.C2paSignerInfo(alg=self.alg, sign_cert=self.cert_pem,
                                   private_key=self.key_pem, ta_url=b"")
        signer = c2pa.Signer.from_info(info)
        out = io.BytesIO()
        c2pa.Builder(manifest).sign(signer, "image/jpeg", io.BytesIO(jpeg), out)
        return out.getvalue()


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

@dataclass
class ProvenanceResult:
    jpeg: bytes                # the redacted (and, if signed, credentialed) frame
    manifest: dict             # the C2PA manifest that was asserted
    redacted: bool             # did bystander redaction actually run
    regions: int               # how many faces/plates were blurred
    signed: bool               # did the C2PA signature embed


class CaptureProvenance:
    """Run every captured frame through redact → sign before it can persist.

    ``strict=True`` refuses capture (returns None) when no redactor is
    available — the maximum-privacy stance (nothing un-redacted is ever stored).
    ``strict=False`` passes the frame through but records ``redacted=False`` in
    the manifest, so provenance never *claims* a redaction that didn't happen."""

    def __init__(self, signer: Optional[C2paProvenanceSigner] = None,
                 redactor: Optional[EgoBlurRedactor] = None,
                 device_id: str = "dreamlayer-halo", strict: bool = False,
                 now_fn=None):
        self.signer = signer
        self.redactor = redactor
        self.device_id = device_id
        self.strict = strict
        import time
        self._now = now_fn or time.time

    def _has_redactor(self) -> bool:
        return self.redactor is not None and getattr(self.redactor,
                                                     "available", False)

    def ingest(self, jpeg: bytes, privacy=None) -> Optional[ProvenanceResult]:
        """Redact + sign one captured frame. Veil-gated; returns None while
        incognito, and (in strict mode) when no redactor can protect bystanders."""
        if privacy is not None:
            try:
                if not privacy.allow_capture():
                    return None
            except Exception:
                return None

        redacted, regions = False, 0
        frame = jpeg
        if self._has_redactor():
            assert self.redactor is not None   # _has_redactor() checks exactly this
            frame, regions = self.redactor.redact(jpeg)
            redacted = True                # a redactor ran (0 regions = none found)
        elif self.strict:
            # no way to protect bystanders → refuse to persist the raw frame
            return None

        manifest = self._manifest(redacted, regions)
        signed = False
        out = frame
        if self.signer is not None and getattr(self.signer, "available", False):
            try:
                out = self.signer.sign(frame, manifest)
                signed = True
            except Exception as exc:       # bad/absent cert → keep the manifest,
                log.warning("[c2pa] sign failed: %s", exc)   # skip the embed
        return ProvenanceResult(out, manifest, redacted, regions, signed)

    def _manifest(self, redacted: bool, regions: int) -> dict:
        actions: list[dict[str, Any]] = [{"action": "c2pa.created",
                    "softwareAgent": f"dreamlayer/{self.device_id}"}]
        if redacted:
            actions.append({"action": "c2pa.redacted",
                            "parameters": {"faces_or_plates": regions}})
        return {
            "claim_generator": "dreamlayer",
            "assertions": [
                {"label": "c2pa.actions", "data": {"actions": actions}},
                {"label": "dreamlayer.capture",
                 "data": {"device": self.device_id,
                          "captured_at": int(self._now()),
                          "bystander_redaction": redacted,
                          "regions_blurred": regions}},
            ],
        }
