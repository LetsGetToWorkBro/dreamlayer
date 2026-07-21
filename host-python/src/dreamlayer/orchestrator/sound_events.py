"""orchestrator/sound_events.py — the glasses that listen to the WORLD (not to people).

voice_guard governs the speech path ("never voiceprint a stranger"); this is its
sibling rung for everything that ISN'T speech. An on-device audio tagger (PANNs,
AudioSet's 527 sound classes) recognises a smoke alarm, a kettle, a doorbell,
glass breaking, a baby crying, a siren — and hands the noteworthy ones to the
attention engine so Juno can tap you: "kettle's boiling," "smoke alarm."

Privacy posture — this is the whole point of the feature:
  * It classifies SOUND TYPES, never voiceprints. A smoke alarm has no identity;
    a doorbell has no identity. Nothing here re-identifies a person.
  * It deliberately ignores speech. The curated attention map contains ONLY
    environmental sounds; a "Speech"/"Conversation" tag never becomes an alert
    (that path is voice_guard's, and it refuses to bank a stranger's biometric).
  * All on-device — audio never leaves the Brain.

Two halves, split like meeting.py's deterministic + optional-model design:
  * `SoundEventDetector.detect(audio, sr)` — the model (lazy, extra `sound-events`);
    absent the wheel it returns [] and nothing listens, exactly as today.
  * `attention_for(detections)` — PURE and deterministic: maps a detection list to
    an attention Alert (or None). Testable with no wheel, and the single place the
    "which sounds are worth interrupting you for" policy lives.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from .attention import Alert

log = logging.getLogger("dreamlayer.sound_events")

_SR = 32000                      # PANNs operates at 32 kHz mono


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


# The attention map: AudioSet-label substrings (lower-cased, matched case-insensitively)
# → (level, the line Juno speaks). Ordered watch-outs first so a genuinely urgent
# sound outranks a merely-notable one. Speech/among-people classes are ABSENT on
# purpose — this rung listens to the world, not to people.
_ATTENTION: Tuple[Tuple[str, str, str], ...] = (
    # --- watch out: time-critical safety ---
    ("smoke detector", "watchout", "Smoke alarm"),
    ("smoke alarm", "watchout", "Smoke alarm"),
    ("fire alarm", "watchout", "Fire alarm"),
    ("carbon monoxide", "watchout", "CO alarm"),
    ("shatter", "watchout", "Glass breaking"),
    ("glass", "watchout", "Glass breaking"),
    ("civil defense siren", "watchout", "Siren"),
    ("smoke", "watchout", "Smoke alarm"),
    ("siren", "watchout", "Siren nearby"),
    # --- listen: worth a glance ---
    ("doorbell", "listen", "Someone's at the door"),
    ("ding-dong", "listen", "Someone's at the door"),
    ("knock", "listen", "A knock at the door"),
    ("kettle", "listen", "Kettle's boiling"),
    ("steam whistle", "listen", "Kettle's boiling"),
    ("whistle", "listen", "A whistle"),
    ("boiling", "listen", "Something's boiling"),
    ("baby cry", "listen", "A baby's crying"),
    ("infant cry", "listen", "A baby's crying"),
    ("crying, sobbing", "listen", "Someone's crying"),
    ("vehicle horn", "listen", "A car horn"),
    ("car horn", "listen", "A car horn"),
    ("honking", "listen", "A car horn"),
    ("alarm clock", "listen", "Your alarm"),
    ("telephone bell", "listen", "A phone's ringing"),
    ("ringtone", "listen", "A phone's ringing"),
    ("bark", "listen", "A dog barking"),
    ("microwave oven", "listen", "The microwave"),
    ("buzzer", "listen", "A buzzer"),
    ("beep, bleep", "listen", "A beeping"),
)

# Sound families we must NEVER turn into an alert here even if a wheel surfaces
# them: anything about a person speaking. Belt-and-suspenders on top of "the map
# only lists environmental sounds" — if a curated line ever overlaps a speech
# tag, this vetoes it. (The speech path is voice_guard's, biometrics-guarded.)
_SPEECH_VETO = ("speech", "conversation", "narration", "monologue",
                "shout", "whisper", "singing", "chatter", "babbling")

_MIN_CONF = 0.15                 # PANNs clipwise probability floor to act on


def _match(label: str) -> Optional[Tuple[str, str]]:
    """(level, clue) for a label that maps to an attention sound, else None. A
    speech-family label is vetoed even if it would otherwise match."""
    lab = (label or "").strip().lower()
    if not lab or any(v in lab for v in _SPEECH_VETO):
        return None
    for needle, level, clue in _ATTENTION:
        if needle in lab:
            return level, clue
    return None


def attention_for(detections, min_conf: float = _MIN_CONF) -> Optional[Alert]:
    """PURE: turn a list of (label, confidence) sound detections into the single
    most important attention Alert, or None when nothing is worth interrupting for.
    Watch-outs (smoke alarm, glass, siren) outrank listens; within a level the
    louder (higher-confidence) detection wins. Deterministic — no model needed."""
    best: Optional[Tuple[int, float, Alert]] = None
    for item in (detections or []):
        try:
            label, conf = item[0], float(item[1])
        except (TypeError, ValueError, LookupError):   # LookupError: a dict item, etc.
            continue
        # `not (conf >= min_conf)` rejects NaN too: a NaN confidence (which numpy's
        # argsort ranks FIRST) would otherwise pass `conf < min_conf` and fire the
        # loudest possible alert — a false smoke-alarm watchout (refute 2026-07-21).
        if not (conf >= min_conf):
            continue
        m = _match(str(label))
        if m is None:
            continue
        level, clue = m
        rank = 0 if level == "watchout" else 1
        alert = Alert(level, clue, "heard nearby", f"sound:{clue.lower()}")
        # lower rank first, then higher confidence — sort key is (rank, -conf)
        key = (rank, -conf, alert)
        if best is None or key[:2] < (best[0], best[1]):
            best = (rank, -conf, alert)
    return best[2] if best else None


class SoundEventDetector:
    """Wrap audio tagging behind ONE detector, on an engine ladder (the same
    shape as Kokoro→Piper): PANNs (panns_inference, AudioSet's full 527 classes)
    first, else sherpa-onnx audio tagging (already in the `voice` extra — no
    torch) with a model dir at $DL_AUDIO_TAG_DIR (model.onnx + labels file).
    `available` is either engine's wheel; `ready` once a tagger actually loaded.
    Note: PANNs fetches its checkpoint on first load — a model-weights download,
    posture-gated like the other local models; audio itself never leaves the
    Brain."""

    dep = "panns_inference"
    available = _has("panns_inference") or _has("sherpa_onnx")

    def __init__(self, sherpa_dir: Optional[str] = None):
        from typing import Any as _Any
        self._tagger: _Any = None    # panns backend
        self._labels: _Any = None
        self._sherpa: _Any = None    # sherpa-onnx backend
        self._loaded = False
        self.backend = ""
        import os
        self._sherpa_dir = sherpa_dir or os.environ.get("DL_AUDIO_TAG_DIR", "")

    def _load(self) -> bool:
        if self._loaded:
            return self._tagger is not None or self._sherpa is not None
        self._loaded = True
        if _has("panns_inference"):
            try:
                from panns_inference import AudioTagging  # type: ignore
                from panns_inference.config import labels  # type: ignore
                self._tagger = AudioTagging(checkpoint_path=None, device="cpu")
                self._labels = list(labels)
                self.backend = "panns"
                return True
            except Exception as exc:             # noqa: BLE001
                log.info("[sound] PANNs load failed: %s; trying sherpa", exc)
                self._tagger = None
        self._load_sherpa()
        return self._tagger is not None or self._sherpa is not None

    def _load_sherpa(self) -> None:
        """The no-torch fallback: sherpa-onnx audio tagging from a local model
        dir. Absent the wheel, the dir, or its files → stays off, never raises."""
        from pathlib import Path
        d = Path(self._sherpa_dir) if self._sherpa_dir else None
        if d is None or not _has("sherpa_onnx"):
            return
        try:
            model = d / "model.onnx"
            labels = next(iter(sorted(d.glob("*.csv"))), None) or (d / "labels.txt")
            if not model.is_file() or not Path(labels).is_file():
                return
            import sherpa_onnx  # type: ignore
            cfg = sherpa_onnx.AudioTaggingConfig(
                model=sherpa_onnx.AudioTaggingModelConfig(
                    zipformer=sherpa_onnx.OfflineZipformerAudioTaggingModelConfig(
                        model=str(model)),
                    num_threads=1),
                labels=str(labels))
            self._sherpa = sherpa_onnx.AudioTagging(cfg)
            self.backend = "sherpa"
        except Exception as exc:                 # noqa: BLE001
            log.info("[sound] sherpa tagger load failed: %s", exc)
            self._sherpa = None

    @property
    def ready(self) -> bool:
        return self._load()

    def detect(self, audio, sample_rate: int = _SR,
               top_k: int = 5) -> List[Tuple[str, float]]:
        """Top-k (label, confidence) sound tags for an audio window, or [] when
        unavailable / on any failure. Never raises into the capture loop."""
        if not self._load():
            return []
        if self._tagger is None and self._sherpa is not None:
            return self._detect_sherpa(audio, sample_rate, top_k)
        mono = _to_mono(audio, sample_rate, _SR)
        if mono is None:
            return []
        try:
            import numpy as np
            out = self._tagger.inference(mono[None, :])
            clip = np.asarray(out[0] if isinstance(out, (list, tuple)) else out)
            clip = clip.reshape(-1)
            if clip.size == 0 or self._labels is None:
                return []
            n = min(int(top_k), clip.size, len(self._labels))
            idx = np.argsort(clip)[::-1][:n]
            return [(str(self._labels[i]), float(clip[i])) for i in idx]
        except Exception as exc:                 # noqa: BLE001
            log.error("[sound] inference failed: %s", exc)
            return []

    def _detect_sherpa(self, audio, sample_rate: int,
                       top_k: int) -> List[Tuple[str, float]]:
        """The sherpa-onnx tagging path (models run at 16 kHz)."""
        mono = _to_mono(audio, sample_rate, 16000)
        if mono is None:
            return []
        try:
            stream = self._sherpa.create_stream()
            stream.accept_waveform(16000, mono)
            events = self._sherpa.compute(stream, max(1, int(top_k)))
            return [(str(getattr(e, "name", "")), float(getattr(e, "prob", 0.0)))
                    for e in (events or []) if getattr(e, "name", "")]
        except Exception as exc:                 # noqa: BLE001
            log.error("[sound] sherpa inference failed: %s", exc)
            return []

    def listen(self, audio, sample_rate: int = _SR) -> Optional[Alert]:
        """Detect + map in one call: the attention Alert for what was heard, or
        None. The orchestrator hands this to the same hark path as any other
        attention Alert (which carries its own Veil/Focus gating + cooldown)."""
        return attention_for(self.detect(audio, sample_rate))


def _to_mono(audio, sample_rate: int, target_sr: int):
    """float32 mono at target_sr in [-1,1], or None. Linear resample (no extra
    dep). Shared shape/scale discipline with rosetta_seamless._to_mono16k."""
    try:
        import numpy as np
        raw = np.asarray(audio)
        is_int = np.issubdtype(raw.dtype, np.integer)
        a = raw.astype(np.float32)
        if a.size == 0:
            return None
        if a.ndim == 2:                          # stereo → mono: collapse the
            a = a.mean(axis=1) if a.shape[1] <= a.shape[0] else a.mean(axis=0)
        a = a.reshape(-1)
        # integer PCM → scale by full-scale; float assumed [-1,1] unless its peak
        # is far past any real float mic signal, i.e. int16 handed in as float
        # (refute 2026-07-21: a plain peak>1.5 test wrecked legitimately-hot float).
        if is_int:
            info = np.iinfo(raw.dtype)
            a = a / float(max(abs(int(info.min)), int(info.max)))
        elif a.size and float(np.max(np.abs(a))) > 32.0:
            a = a / 32768.0
        sr = int(sample_rate or target_sr)
        if sr != target_sr and a.size:
            n_out = int(round(a.size * target_sr / sr))
            if n_out <= 0:
                return None
            xp = np.linspace(0.0, 1.0, num=a.size, endpoint=False)
            xq = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
            a = np.interp(xq, xp, a).astype(np.float32)
        return np.clip(a, -1.0, 1.0)
    except Exception as exc:                     # noqa: BLE001
        log.debug("[sound] audio coerce failed: %s", exc)
        return None


def default_sound_detector() -> Optional[SoundEventDetector]:
    d = SoundEventDetector()
    return d if d.available else None
