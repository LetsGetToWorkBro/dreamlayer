"""soundlink.py — data over sound (ggwave): pair without a QR code.

ggwave (from the llama.cpp author) turns a short text payload into an audio
"chirp" — an FSK tone burst, optionally in the NEAR-ULTRASONIC band humans barely
hear — and back again. DreamLayer uses it as a QR-free pairing fallback: the
Brain *sings* the short single-use pairing code, and a phone in earshot catches
it out of the air. It is a fallback, never the only path — absent the wheel,
`available` is False, every method returns a clean neutral, and the QR/typed-code
flows are untouched.

Posture: the chirp carries ONLY the same short, single-use, 5-minute pairing code
the QR already encodes — never the token, never memory. A sung code is exactly as
sensitive as a QR held up to the room (a shoulder-surfer could read either), and
the redeem path is single-use + rate-limited + globally attempt-capped, so an
overheard code is spent or expired before it is useful.

Lazy adapter (extras group `soundlink`); ggwave's default waveform is float32
mono @ 48 kHz (matching its own examples), which `encode_wav` wraps as a
16-bit WAV any browser <audio> element can play.
"""
from __future__ import annotations

import io
import logging
import wave
from typing import Optional

log = logging.getLogger("dreamlayer.soundlink")

SOUND_TAG = "dl:"                # marks a chirp as OURS (not stray room audio)
SAMPLE_RATE = 48000              # ggwave's native rate (its examples use 48 kHz)
# ggwave protocol ids: 1 = audible "Fast"; 4 = near-ultrasonic "[U] Fast" — the
# one humans barely hear, so a pairing chirp doesn't fill the room with beeps.
PROTO_AUDIBLE = 1
PROTO_ULTRASOUND = 4
_MAX_PAYLOAD = 140               # ggwave's single-transmission byte ceiling


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


class SoundLink:
    """Encode a short payload to a ggwave waveform and decode one back. Absent
    the wheel, `available` is False and encode/decode return b"" / "" — so the
    caller keeps whatever non-sound path it had."""

    dep = "ggwave"
    available = _has("ggwave")

    def __init__(self, ultrasound: bool = True, volume: int = 20):
        # near-ultrasonic by default: the pairing chirp is meant to be caught,
        # not heard across a café.
        self.protocol = PROTO_ULTRASOUND if ultrasound else PROTO_AUDIBLE
        self.volume = max(1, min(int(volume), 100))
        self._inst = None            # decode instance, created lazily

    # -- encode ---------------------------------------------------------

    def encode(self, text: str) -> bytes:
        """Text → a ggwave waveform (float32 PCM @ 48 kHz, as raw bytes). b""
        when unavailable, empty, or the payload exceeds ggwave's frame ceiling."""
        text = text or ""
        if not text or not self.available:
            return b""
        nbytes = len(text.encode("utf-8", "replace"))
        if nbytes > _MAX_PAYLOAD:
            log.info("[soundlink] payload too long for one chirp (%d bytes)", nbytes)
            return b""
        try:
            import ggwave
            wav = ggwave.encode(text, protocolId=self.protocol, volume=self.volume)
            return wav or b""
        except Exception as exc:                       # noqa: BLE001 — never raise
            log.info("[soundlink] encode failed: %s", exc)
            return b""

    def encode_wav(self, text: str) -> bytes:
        """Text → a self-contained 16-bit mono WAV (@ 48 kHz) a browser <audio>
        element can play directly. b"" when unavailable. ggwave emits float32
        samples; we clip to [-1, 1] and quantise to int16 so the file plays
        everywhere without a float-WAV codec."""
        raw = self.encode(text)
        if not raw:
            return b""
        try:
            import numpy as np
            f32 = np.frombuffer(raw, dtype=np.float32)
            i16 = (np.clip(f32, -1.0, 1.0) * 32767.0).astype("<i2")
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(i16.tobytes())
            return buf.getvalue()
        except Exception as exc:                       # noqa: BLE001
            log.info("[soundlink] wav wrap failed: %s", exc)
            return b""

    # -- decode ---------------------------------------------------------

    def _instance(self):
        if self._inst is None and self.available:
            try:
                import ggwave
                self._inst = ggwave.init()
            except Exception as exc:                   # noqa: BLE001
                log.info("[soundlink] init failed: %s", exc)
                self._inst = None
        return self._inst

    def decode(self, waveform) -> str:
        """A chunk of captured audio (float32 PCM @ 48 kHz — raw bytes, or a
        list/array of floats) → the decoded payload, or "" when nothing decodes.
        Never raises into the capture loop."""
        inst = self._instance()
        if inst is None or waveform is None:
            return ""
        data = self._as_f32_bytes(waveform)
        if not data:
            return ""
        try:
            import ggwave
            out = ggwave.decode(inst, data)
            if not out:
                return ""
            return out.decode("utf-8", "replace") if isinstance(out, (bytes, bytearray)) \
                else str(out)
        except Exception as exc:                       # noqa: BLE001
            log.info("[soundlink] decode failed: %s", exc)
            return ""

    @staticmethod
    def _as_f32_bytes(waveform) -> bytes:
        """Coerce a float list/array or raw bytes to float32 little-endian bytes
        (what ggwave.decode expects), or b"" on anything unusable."""
        if isinstance(waveform, (bytes, bytearray)):
            return bytes(waveform)
        try:
            import numpy as np
            return np.asarray(list(waveform), dtype="<f4").tobytes()
        except Exception:                              # noqa: BLE001
            return b""

    def close(self) -> None:
        if self._inst is not None:
            try:
                import ggwave
                ggwave.free(self._inst)
            except Exception:                          # noqa: BLE001
                pass
            self._inst = None


def default_soundlink(ultrasound: bool = True) -> Optional[SoundLink]:
    """A SoundLink when ggwave is installed, else None (so a caller can fall back
    to the QR/typed-code pairing path)."""
    s = SoundLink(ultrasound=ultrasound)
    return s if s.available else None
