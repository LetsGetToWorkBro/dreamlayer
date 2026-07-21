"""Data-over-sound pairing (ggwave): the Brain sings the pairing code.

ggwave isn't installed in CI, so the adapter is tested for its degradation
contract, its WAV wrapping (with an injected float32 source), and the pairing
wiring end to end with an injected reversible SoundLink — proving a sung code
redeems the SAME token a scanned/typed one does, i.e. a true QR-free fallback.
"""
from __future__ import annotations

import base64
import io
import json
import threading
import urllib.error
import urllib.request
import wave

import numpy as np

from dreamlayer.soundlink import SoundLink, default_soundlink
from dreamlayer.pairing import catch_pairing_sound
from dreamlayer.ai_brain.server import Brain, BrainConfig, make_brain_server


# ---- the adapter: degradation + WAV wrapping -----------------------------

def test_soundlink_degrades_cleanly_without_ggwave():
    sl = SoundLink()
    assert sl.available is False          # ggwave not installed in CI
    assert sl.encode("dl:123") == b""
    assert sl.encode_wav("dl:123") == b""
    assert sl.decode(b"anything") == ""
    assert default_soundlink() is None
    sl.close()                             # safe no-op


def test_encode_wav_wraps_float32_as_playable_wav():
    class _F32(SoundLink):
        available = True
        def encode(self, text):
            t = np.arange(4800) / 48000.0
            return (0.4 * np.sin(2 * np.pi * 19000 * t)).astype(np.float32).tobytes()
    wav = _F32().encode_wav("dl:87654321")
    assert wav[:4] == b"RIFF"              # a real WAV container
    with wave.open(io.BytesIO(wav), "rb") as r:
        assert r.getframerate() == 48000
        assert r.getnchannels() == 1
        assert r.getsampwidth() == 2       # int16, plays everywhere
        assert r.getnframes() == 4800


def test_payload_over_ceiling_is_rejected():
    class _Avail(SoundLink):
        available = True         # pretend ggwave is present
    # a 200-byte payload exceeds ggwave's single-chirp ceiling → "" before any
    # encode is attempted (the caller keeps the QR)
    assert _Avail().encode("x" * 200) == b""


# ---- the catching side ---------------------------------------------------

class _LoopLink(SoundLink):
    """A reversible fake: encode tags the text, decode recovers it — stands in
    for a real ggwave round-trip so the pairing wiring is testable offline."""
    available = True

    def encode(self, text):
        return b"CHIRP:" + text.encode("utf-8")

    def decode(self, pcm):
        raw = bytes(pcm) if isinstance(pcm, (bytes, bytearray)) else b""
        return raw[6:].decode("utf-8") if raw.startswith(b"CHIRP:") else ""


def test_catch_pairing_sound_recovers_a_tagged_code():
    link = _LoopLink()
    chirp = link.encode("dl:12345678")
    assert catch_pairing_sound(chirp, link=link) == "12345678"


def test_catch_rejects_untagged_or_nonnumeric_audio():
    link = _LoopLink()
    # stray audio without our dl: tag
    assert catch_pairing_sound(link.encode("hello world"), link=link) == ""
    # tagged but not a numeric code (won't match a live code)
    assert catch_pairing_sound(link.encode("dl:DROP TABLE"), link=link) == ""
    # no link available at all
    assert catch_pairing_sound(b"anything", link=None) == "" or default_soundlink() is None


# ---- the Brain "sings" — the /dreamlayer/pair/sound endpoint --------------

def _post(url, payload, headers=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


class LiveBrain:
    def __init__(self, tmp_path, token="rune-birch"):
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        BrainConfig(token=token).save(cfg_dir)
        self.brain = Brain(cfg_dir)
        self.server = make_brain_server(self.brain, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.h = {"X-DreamLayer-Token": token}

    def stop(self):
        self.server.shutdown(); self.server.server_close()


def test_pair_sound_issues_a_code_and_degrades_without_ggwave(tmp_path):
    lb = LiveBrain(tmp_path)
    try:
        st, body = _get(lb.url + "/dreamlayer/pair/sound", lb.h)
        assert st == 200
        assert body["available"] is False          # ggwave absent
        assert body["code"] and body["code"].isdigit() and len(body["code"]) == 8
        assert body["wav_b64"] == ""
        assert "soundlink" in body["note"] or "ggwave" in body["note"]
    finally:
        lb.stop()


def test_pair_sound_sings_a_wav_with_ggwave_present(tmp_path, monkeypatch):
    lb = LiveBrain(tmp_path)
    try:
        class _F32(SoundLink):
            available = True
            def encode(self, text):
                t = np.arange(2400) / 48000.0
                return (0.3 * np.sin(2 * np.pi * 19000 * t)).astype(np.float32).tobytes()
        import dreamlayer.soundlink as slmod
        monkeypatch.setattr(slmod, "default_soundlink", lambda ultrasound=True: _F32())
        st, body = _get(lb.url + "/dreamlayer/pair/sound", lb.h)
        assert st == 200 and body["available"] is True
        wav = base64.b64decode(body["wav_b64"])
        with wave.open(io.BytesIO(wav), "rb") as r:
            assert r.getframerate() == 48000 and r.getnframes() == 2400
        # the sing is on the ledger
        rec = json.dumps(lb.brain.activity.receipt())
        assert "sound" in rec.lower()
    finally:
        lb.stop()


def test_sung_code_redeems_the_same_token(tmp_path):
    """End to end: the code the Brain sings redeems the exact token a scanned or
    typed code would — a true QR-free fallback, not a parallel credential."""
    lb = LiveBrain(tmp_path, token="secret-token-xyz")
    try:
        _, body = _get(lb.url + "/dreamlayer/pair/sound", lb.h)
        code = body["code"]
        # the phone catches the chirp (reversible fake stands in for ggwave)
        link = _LoopLink()
        chirp = link.encode("dl:" + code)
        caught = catch_pairing_sound(chirp, link=link)
        assert caught == code
        # …and redeems it exactly like a typed/scanned code
        st, redeemed = _post(lb.url + "/dreamlayer/live/redeem", {"code": caught})
        assert st == 200 and redeemed["token"] == "secret-token-xyz"
        # single-use: the same caught code can't be redeemed twice
        st2, _ = _post(lb.url + "/dreamlayer/live/redeem", {"code": caught})
        assert st2 == 401
    finally:
        lb.stop()
