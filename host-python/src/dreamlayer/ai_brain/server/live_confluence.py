"""live_confluence.py — the shared sky, between two Live Lens phones.

Confluence is Dream Mode's two-wearer layer: two entangled skies blending or
splitting by how *together* the two inner weathers are. On the glasses the
packets ride a bond between two devices; pre-hardware, the Brain plays the
one honest role it can — the MEETING POINT. Two phones dreaming on this
Brain's Live Lens exchange their weather through it, and everything that
matters runs on the REAL primitives, not a re-implementation:

  * :class:`~dreamlayer.confluence.bond.BondManager` — the three-step mutual
    opt-in (propose → a three-word code the two humans SPEAK to each other →
    accept → confirm), HMAC-authenticated packets keyed off (bond_id, code),
    replay protection, and a sender silenced by the veil;
  * :class:`~dreamlayer.confluence.entangle.EntangledSky` — one per side:
    the togetherness EMA, the merged/split hysteresis band, the stale-peer
    fade, and the exact frames the glasses draw (a blended palette when
    merged; ``seam_dd``/``gap_deg``/``peer_rgb`` when split).

The room is in-memory only: no bond, code, or weather ever touches disk or
the activity ledger. A session silent for :data:`SESSION_STALE_S` is
dropped; unaccepted offers expire; the whole room is capped. The wearer's
posture gates both directions through the same allow_capture/allow_recall
contract the glasses honor (incognito → the sender goes quiet and the sky
renders nothing — EntangledSky enforces it, not this file).
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from ...confluence.bond import BondManager
from ...confluence.entangle import EntangledSky

ROOM_MAX = 8              # sessions with live confluence state, per Brain
SESSION_STALE_S = 60.0    # silent this long → the session is dropped
OFFER_TTL_S = 600.0       # an unaccepted code dies after 10 minutes


class _PostureGate:
    """The Brain's incognito posture, shaped like the privacy gate the real
    BondManager/EntangledSky expect (capture gates the sender, recall gates
    folding the peer's weather in). Fails closed on an unreadable posture."""

    def __init__(self, brain) -> None:
        self._brain = brain

    def allow_capture(self) -> bool:
        try:
            return not bool(self._brain.incognito_now())
        except Exception:
            return False

    def allow_recall(self) -> bool:
        return self.allow_capture()


class LiveConfluence:
    """The per-Brain confluence room. Thread-safe; every public method returns
    plain JSON-ready dicts for the live routes."""

    def __init__(self, brain, now_fn=time.time) -> None:
        self._brain = brain
        self._now = now_fn
        self._lock = threading.Lock()
        self._gate = _PostureGate(brain)
        # sid -> {mgr, sky, seen, peer (sid|None), inbox (wire|None), bond_id}
        self._sessions: dict = {}
        # bond_id -> {sid, code, ts} — the code lives ONLY until accepted,
        # only in memory, only so the accept can answer "wrong code" honestly
        self._offers: dict = {}

    # -- internals ---------------------------------------------------------

    def _prune(self) -> None:
        now = self._now()
        for bond_id in [b for b, o in self._offers.items()
                        if now - o["ts"] > OFFER_TTL_S]:
            self._offers.pop(bond_id, None)
        for sid in [s for s, v in self._sessions.items()
                    if now - v["seen"] > SESSION_STALE_S]:
            v = self._sessions.pop(sid)
            peer = self._sessions.get(v.get("peer"))
            if peer is not None:
                peer["peer"] = None       # their sky stale-fades on its own

    def _session(self, sid: str) -> Optional[dict]:
        s = self._sessions.get(sid)
        if s is not None:
            s["seen"] = self._now()
        return s

    # -- the three-step opt-in --------------------------------------------

    def propose(self, sid: str) -> dict:
        sid = (sid or "").strip()
        if not sid:
            return {"error": "no session id"}
        with self._lock:
            self._prune()
            if sid not in self._sessions and len(self._sessions) >= ROOM_MAX:
                return {"error": "the room is full"}
            mgr = BondManager(privacy=self._gate, now_fn=self._now)
            offer = mgr.propose(label="live-lens")
            self._sessions[sid] = {"mgr": mgr, "sky": None, "peer": None,
                                   "inbox": None, "bond_id": offer.bond_id,
                                   "seen": self._now()}
            self._offers[offer.bond_id] = {"sid": sid, "code": offer.code,
                                           "ts": self._now()}
            return {"ok": True, "code": offer.code}

    def accept(self, sid: str, code: str) -> dict:
        sid = (sid or "").strip()
        code = "-".join((code or "").lower().split()).strip("-")
        if not sid or not code:
            return {"error": "no session id or code"}
        with self._lock:
            self._prune()
            if sid not in self._sessions and len(self._sessions) >= ROOM_MAX:
                return {"error": "the room is full"}
            match = next((b for b, o in self._offers.items()
                          if o["code"] == code and o["sid"] != sid), None)
            if match is None:
                return {"error": "no open offer matches that code"}
            offer = self._offers.pop(match)
            a = self._sessions.get(offer["sid"])
            if a is None:
                return {"error": "the proposer left"}
            # the REAL three-step: accept on this side, confirm on theirs —
            # both keys derive from (bond_id, code); every packet is MAC'd
            b_mgr = BondManager(privacy=self._gate, now_fn=self._now)
            b_mgr.accept(match, offer["code"], label="live-lens")
            a["mgr"].confirm(match)
            a["sky"] = EntangledSky(a["mgr"], now_fn=self._now,
                                    privacy=self._gate)
            b_sky = EntangledSky(b_mgr, now_fn=self._now, privacy=self._gate)
            self._sessions[sid] = {"mgr": b_mgr, "sky": b_sky,
                                   "peer": offer["sid"], "inbox": None,
                                   "bond_id": match, "seen": self._now()}
            a["peer"] = sid
            return {"ok": True}

    def dissolve(self, sid: str) -> dict:
        with self._lock:
            s = self._sessions.pop((sid or "").strip(), None)
            if s is None:
                return {"ok": True}
            try:
                s["mgr"].dissolve(s.get("bond_id") or "")
            except Exception:
                pass
            self._offers.pop(s.get("bond_id") or "", None)
            peer = self._sessions.get(s.get("peer"))
            if peer is not None:
                peer["peer"] = None
            return {"ok": True}

    # -- the only traffic --------------------------------------------------

    def weather(self, sid: str, state: float, colors: list) -> dict:
        """One 2 Hz beat from one side: package my weather for the peer
        (HMAC'd, veil-silenced), fold in anything the peer sent, tick MY
        EntangledSky, and hand back the frames my glass would draw."""
        try:
            state = max(0.0, min(1.0, float(state)))
        except (TypeError, ValueError):
            return {"error": "bad state"}
        if not isinstance(colors, list):
            colors = []
        colors = colors[:4]
        with self._lock:
            self._prune()
            s = self._session((sid or "").strip())
            if s is None:
                return {"entangled": False, "frames": []}
            peer = self._sessions.get(s.get("peer"))
            pkt = s["mgr"].send_weather(state, colors)
            if pkt is not None and peer is not None:
                peer["inbox"] = pkt.to_wire()
            wire = s.get("inbox")
            s["inbox"] = None
            sky = s.get("sky")
            if sky is None:
                return {"entangled": False, "frames": [],
                        "waiting": bool(s.get("bond_id") in self._offers)}
            if wire is not None:
                sky.receive(wire)
            frames = sky.tick(state, colors)
            return {"entangled": True,
                    "peer_live": bool(sky.peer_present()),
                    "frames": frames}


def room(brain) -> LiveConfluence:
    """The Brain's confluence room, created on first use and cached on the
    Brain instance (the same lifetime pattern as the cached world-lens host —
    erase/restart drops it, and the room holds no durable state anyway)."""
    r = getattr(brain, "_live_confluence", None)
    if r is None:
        r = LiveConfluence(brain)
        brain._live_confluence = r
    return r
