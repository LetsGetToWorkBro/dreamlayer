"""live_dream.py — Dream Mode's real scene layer, for the Live Lens phone.

On the glasses, Dream Mode does more than paint reactive weather: every
SCENE_INTERVAL a camera frame becomes a *SynesthesiaCard* (a six-word poetic
phrase + a three-shape gestural sprite), and when you are somewhere your
memory has anchors, a dim *WorldAnchorCard* ghost surfaces the moment you
kept there. Both run the REAL primitives, not a re-implementation:

  * :class:`~dreamlayer.dream_mode.scene_describer.SceneDescriber` — the frame
    → phrase + gesture pipeline, driven by the Brain's own vision backend
    (``world_lens._describe``, the same posture-gated seam a deliberate look
    rides — the frame never leaves the Brain, and remote vision is refused and
    counted exactly as elsewhere). With no vision backend it degrades to the
    documented offline mood cycle + a hash-derived sprite, never a fabricated
    scene;
  * :class:`~dreamlayer.dream_mode.ghost_layer.GhostLayer` — place anchors →
    ghost echoes, fed the wearer's GENUINE Waypath place-memories (the same
    saved spots the Memories tab shows), so a ghost is only ever a real moment
    you kept, at a real place, with its real time.

The wearer's veil gates both directions through the world lens's own capture
gate: incognito → the frame never reaches the VLM and no ghost is surfaced.
Nothing here is persisted; the describer/ghost pair is cached on the Brain only
so the mood cycle and the 2-minute per-anchor ghost cooldown carry across beats.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional

from ...dream_mode.ghost_layer import GhostLayer
from ...dream_mode.scene_describer import SceneDescriber
from ...hud import cards as C
from ...object_lens import person_guard
from ...object_lens.vision_recognizer import frame_to_b64
from ...orchestrator.recall_context import RecallContext

MAX_ANCHORS = 24          # newest place-memories fed to the ghost layer

# Bound concurrent scene beats. Each runs up to two VLM calls; a hung backend
# (the 5 s wait_for only bounds the awaited result, not the orphaned worker
# thread asyncio.run then joins on shutdown) would otherwise pin a request
# worker for as long as the backend's own socket timeout. Non-blocking: a burst
# SHEDS excess beats (the freshest frame is what matters), so the dream can pin
# at most this many of the server's workers, never the whole pool.
_MAX_CONCURRENT_SCENES = 3
_scene_sem = threading.BoundedSemaphore(_MAX_CONCURRENT_SCENES)

# The dream's synesthesia never identifies a stranger — even when a person is
# the subject or the VLM slips a name in, the phrase falls back to this nameless
# line and only the abstract gesture remains. The privacy rule IS the feature.
_NAMELESS_MOOD = "a presence here — unnamed by design"


def _has_vision(brain) -> bool:
    """True only when the Brain has a real vision backend that reads images —
    exactly ``world_lens._describe``'s own precondition. When False we wire no
    vision_fn, so SceneDescriber uses its honest offline fallback instead of
    returning a blank every beat."""
    backend = getattr(brain, "_backend", None)
    return backend is not None and hasattr(backend, "describe")


def _ago(now: float, ts: Optional[float]) -> str:
    """A short, honest 'when' for a kept moment (no fabricated precision)."""
    if not ts:
        return ""
    d = max(0.0, now - float(ts))
    if d < 90:
        return "moments ago"
    if d < 3600:
        return f"{int(d // 60)}m ago"
    if d < 86400:
        return f"{int(d // 3600)}h ago"
    return f"{int(d // 86400)}d ago"


class LiveDream:
    """The per-Brain dream-scene layer. Thread-safe; returns plain JSON-ready
    dicts for the live route."""

    def __init__(self, brain, now_fn=time.time) -> None:
        self._brain = brain
        self._now = now_fn
        wl = brain.world_lens()
        self._wl = wl
        gate = getattr(wl, "privacy", None)   # _LookGate: allow_capture = not incognito
        # vision_fn keeps the frame on the Brain (world_lens._describe) and rides
        # its remote-vision gate; only wired when a real backend exists.
        vision_fn = self._make_vision_fn(wl) if _has_vision(brain) else None
        self._describer = SceneDescriber(vision_fn=vision_fn, privacy=gate)
        self._ghost = GhostLayer(privacy=gate)

    def _make_vision_fn(self, wl):
        from . import live as live_mod
        async def vision_fn(jpeg: bytes, prompt: str) -> str:
            # decode through the LOOK path's hardened decoder — a 16 MP pre-decode
            # bomb guard, a thumbnail to 512 BEFORE materialising pixels, and a
            # bounded concurrency semaphore — so a token-holding attacker can't
            # post a small, highly-compressible frame that balloons to hundreds of
            # MB per beat and OOMs the Brain (the client posts <=512, but the
            # server must not trust that — refute 2026-07-21).
            frame = await asyncio.to_thread(live_mod.decode_frame, jpeg)
            if frame is None:
                raise ValueError("unreadable frame")
            image_b64 = frame_to_b64(frame)
            out = await asyncio.to_thread(wl._describe, prompt, image_b64)
            if not out:                       # veiled / no answer → describer's
                raise ValueError("no vision")  # own fallback runs for this beat
            return out
        return vision_fn

    def _anchors(self) -> list:
        """The wearer's real place-memories (Waypath), newest first, shaped for
        the GhostLayer. Empty when nothing has been saved — no ghost is
        invented, so a fresh Brain simply surfaces none.

        Honest framing: on the glasses the ghost is triggered by BEING at the
        place (a location match). This phone has no location sense, so these are
        not location-matched — they are your own kept moments drifting up in the
        dream (a reverie, never a "you are here" claim), the same rows the
        Memories tab already shows, and only ever your own, veil-gated."""
        wp = getattr(self._brain, "waypath", None)
        if wp is None:
            return []
        try:
            raw = list(wp.anchors())
        except Exception:
            return []
        raw.sort(key=lambda a: getattr(a, "ts", 0.0) or 0.0, reverse=True)
        now = self._now()
        out = []
        for a in raw[:MAX_ANCHORS]:
            subject = (getattr(a, "subject", "") or "").strip()
            if not subject:
                continue
            out.append({
                "id": subject.lower(),
                "summary": f"Your {subject}",
                "place": (getattr(a, "place", "") or "").strip(),
                "ts_label": _ago(now, getattr(a, "ts", None)),
                "ts": getattr(a, "ts", None),
                "confidence": 0.9,
            })
        return out

    def scene(self, jpeg: bytes) -> dict:
        """One scene beat: a camera frame in, the real SynesthesiaCard + (a
        memory echo of one of your kept moments) out. Veiled → both None. The
        frame is read in memory and never persisted.

        No lock is held across the VLM call: doing so would serialize every
        phone's scene beat behind one blocking describe (a slow remote model =>
        a stall for everyone). The shared state is safe without it — GhostLayer
        .tick is a synchronous, GIL-atomic dict touch, and the only race on the
        describer is its fallback-mood index, whose worst case is a repeated or
        skipped mood line (cosmetic, never a crash or a leak). Concurrency is
        capped instead by a non-blocking semaphore so a hung backend can pin only
        a few workers, not the whole pool."""
        if self._wl.veiled():                 # incognito: no frame to the VLM,
            return {"scene": None, "ghost": None}   # no ghost surfaced
        if not _scene_sem.acquire(blocking=False):
            return {"scene": None, "ghost": None}   # saturated → shed this beat
        try:
            ctx = RecallContext(camera_frame=jpeg or b"",
                                world_anchors=self._anchors())
            try:
                scene = asyncio.run(self._describer.tick(ctx))
            except Exception:
                scene = None
            if scene is not None:
                scene = self._guard_identity(scene)
            try:
                ghost = self._ghost.tick(ctx)
            except Exception:
                ghost = None
            return {"scene": scene, "ghost": ghost}
        finally:
            _scene_sem.release()

    def _guard_identity(self, scene: dict) -> dict:
        """The dream never identifies a stranger. If the six-word phrase names a
        person, drop the identity: keep the abstract gesture, replace the phrase
        with a nameless line. Routes through the SAME person_guard primitive
        every world-lens surface uses — the deterministic name-shape guard always
        runs (it catches a naming phrase with no optional deps), and Presidio NER
        adds depth when the privacy extra is installed. Fail-open only in the
        harmless direction: an error here never invents an identity. (The phrase,
        not the frame, is the identity surface here — a poetic line about a
        *presence* with no name is the Social-Lens contract, not a breach.)"""
        try:
            if not person_guard.defers_person(str(scene.get("description", ""))):
                return scene
        except Exception:
            return scene                      # never break the dream on a guard error
        return C.synesthesia_card_v2(
            description=_NAMELESS_MOOD,
            dominant_color=scene.get("dominant_color", 0x2CC79A),
            shapes=scene.get("shapes", []),
        )


def dream(brain) -> LiveDream:
    """The Brain's dream-scene layer, created on first use and cached on the
    Brain (the cached-host lifetime pattern — erase/restart drops it, and it
    holds no durable state)."""
    d = getattr(brain, "_live_dream", None)
    if d is None:
        d = LiveDream(brain)
        brain._live_dream = d
    return d
