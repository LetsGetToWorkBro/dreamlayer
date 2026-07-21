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
        except (TypeError, ValueError, IndexError):
            continue
        if conf < min_conf:
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
    """Wrap PANNs audio tagging. `available` is the wheel; `ready` is True once the
    tagger (and its checkpoint) have loaded. Loading is lazy. Note: PANNs fetches a
    model checkpoint on first load — a model-weights download, posture-gated like
    the other local models; audio itself never leaves the Brain."""

    dep = "panns_inference"
    available = _has("panns_inference")

    def __init__(self):
        self._tagger = None
        self._labels = None
        self._loaded = False

    def _load(self) -> bool:
        if self._loaded:
            return self._tagger is not None
        self._loaded = True
        if not self.available:
            return False
        try:
            from panns_inference import AudioTagging  # type: ignore
            from panns_inference.config import labels  # type: ignore
            self._tagger = AudioTagging(checkpoint_path=None, device="cpu")
            self._labels = list(labels)
        except Exception as exc:                 # noqa: BLE001
            log.info("[sound] PANNs load failed: %s; sound sense off", exc)
            self._tagger = None
        return self._tagger is not None

    @property
    def ready(self) -> bool:
        return self._load()

    def detect(self, audio, sample_rate: int = _SR,
               top_k: int = 5) -> List[Tuple[str, float]]:
        """Top-k (label, confidence) sound tags for an audio window, or [] when
        unavailable / on any failure. Never raises into the capture loop."""
        if not self._load():
            return []
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
        a = np.asarray(audio, dtype=np.float32)
        if a.size == 0:
            return None
        if a.ndim == 2:
            a = a.mean(axis=1)
        a = a.reshape(-1)
        peak = float(np.max(np.abs(a))) if a.size else 0.0
        if peak > 1.5:                           # looks like int16 PCM → normalise
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
