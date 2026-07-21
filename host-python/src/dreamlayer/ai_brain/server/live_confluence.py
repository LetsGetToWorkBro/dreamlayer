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
from collections import namedtuple
from typing import Optional

from ...confluence.bond import BondManager
from ...confluence.entangle import EntangledSky
from ...confluence.gift import unwrap_gift, wrap_gift

ROOM_MAX = 8              # sessions with live confluence state, per Brain
SESSION_STALE_S = 60.0    # silent this long → the session is dropped
OFFER_TTL_S = 600.0       # an unaccepted code dies after 10 minutes

# The Weather Gift primitive wants a WeatherLedger snapshot; on the Live Lens
# the "moment" being gifted is the sender's CURRENT sky, so we hand it a minimal
# snapshot of (colors, ts) — the same two fields wrap_gift reads.
_GiftSnap = namedtuple("_GiftSnap", ["colors", "ts"])


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

    @staticmethod
    def _clean_colors(colors: list) -> list:
        """Sanitize the four palette slots from one side to the device's 10-bit
        YCbCr shape. A malformed slot is dropped, never allowed to reach the
        engine and 500 the peer's beats (refute 2026-07-21)."""
        if not isinstance(colors, list):
            return []
        clean: list = []
        for c in colors[:4]:
            if not isinstance(c, dict):
                continue
            try:
                clean.append({"idx": int(c.get("idx", 0)),
                              "y": max(0, min(1023, int(c.get("y", 512)))),
                              "cb": max(0, min(1023, int(c.get("cb", 512)))),
                              "cr": max(0, min(1023, int(c.get("cr", 512))))})
            except (TypeError, ValueError):
                continue
        return clean

    # -- the three-step opt-in --------------------------------------------

    def propose(self, sid: str) -> dict:
        sid = (sid or "").strip()
        if not sid:
            return {"error": "no session id"}
        with self._lock:
            self._prune()
            if sid not in self._sessions and len(self._sessions) >= ROOM_MAX:
                return {"error": "the room is full"}
            prior = self._sessions.get(sid)
            if prior is not None:            # re-propose: the old offer dies with
                self._offers.pop(prior.get("bond_id") or "", None)   # the old bond
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
            now = self._now()
            # wrong-code throttle: the two-word space is small, and a wrong
            # code returns a 200-level answer the auth limiter never sees —
            # bound total guesses per room window (refute 2026-07-21)
            self._accept_fails = [t for t in getattr(self, "_accept_fails", [])
                                  if now - t < 60.0]
            if len(self._accept_fails) >= 10:
                return {"error": "too many wrong codes — wait a minute"}
            if sid not in self._sessions and len(self._sessions) >= ROOM_MAX:
                return {"error": "the room is full"}
            matches = [b for b, o in self._offers.items()
                       if o["code"] == code and o["sid"] != sid]
            if len(matches) > 1:             # a collision must never bond to an
                return {"error": "that code is ambiguous right now — mint a fresh one"}   # arbitrary offer
            match = matches[0] if matches else None
            if match is None:
                self._accept_fails.append(now)
                return {"error": "no open offer matches that code"}
            offer = self._offers.pop(match)
            a = self._sessions.get(offer["sid"])
            if a is None:
                return {"error": "the proposer left"}
            if a["mgr"].bond(match) is None:  # a stale offer from a replaced
                return {"error": "that offer expired — mint a fresh one"}   # manager (refute: KeyError 500)
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

    def weather(self, sid: str, state: float, colors: list,
                resync: bool = False) -> dict:
        """One 2 Hz beat from one side: package my weather for the peer
        (HMAC'd, veil-silenced), fold in anything the peer sent, tick MY
        EntangledSky, and hand back the frames my glass would draw."""
        try:
            state = max(0.0, min(1.0, float(state)))
        except (TypeError, ValueError):
            return {"error": "bad state"}
        colors = self._clean_colors(colors)
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
            # a Weather Gift the peer handed me plays FIRST: it is the
            # deliberate, must-not-drop event, and unwrap advances the shared
            # replay counter — folding a lower-seq weather beat after it is a
            # harmless dropped tick, the reverse would replay-drop the gift
            gift_frames = self._receive_gift(s)
            if resync:                       # a client re-entering dream mid-bond
                sky._last_emit_tg = None     # would otherwise stare at a blank
            if wire is not None:             # overlay until togetherness MOVES
                sky.receive(wire)
            try:
                frames = sky.tick(state, colors)
            except Exception:                # the engine never 500s a beat
                frames = []
            return {"entangled": True,
                    "peer_live": bool(sky.peer_present()),
                    "frames": gift_frames + frames}

    def _receive_gift(self, s: dict) -> list:
        """Pop and authenticate a gift the peer left in this session's inbox.
        Returns at most one ``{"t": "gift", ...}`` frame the client plays as a
        timed wash, or ``[]``. Recall-gated (a paused wearer plays nothing even
        from an authentic gift) and forgery-proof (unwrap runs the real
        HMAC/replay/bond-live checks)."""
        gwire = s.pop("inbox_gift", None)
        if gwire is None:
            return []
        played = unwrap_gift(s["mgr"], gwire, privacy=self._gate)
        if not played:
            return []
        # unwrap returns GIFT_PLAY_S/GIFT_FRAME_EVERY_S identical palette frames;
        # the client already renders the palette, so one gift frame carries the
        # colors and it runs the 30 s countdown itself
        return [{"t": "gift", "colors": played[0].get("colors") or []}]

    def gift(self, sid: str, colors: list) -> dict:
        """Hand my CURRENT sky across the bond as a Weather Gift — a 30-second
        wash on the peer's glass, "this is what my moment felt like", then their
        own weather flows back. One authenticated palette snapshot + an hour
        label crosses (never place, never events); the veil silences the sender
        and a stranger's radio can't forge it. The real confluence.gift
        primitive underneath — nothing faked here."""
        colors = self._clean_colors(colors)
        with self._lock:
            self._prune()
            s = self._session((sid or "").strip())
            if s is None:
                return {"ok": False, "error": "not in a shared sky"}
            peer = self._sessions.get(s.get("peer"))
            if peer is None:
                return {"ok": False, "error": "no one to give to yet"}
            wire = wrap_gift(s["mgr"], _GiftSnap(colors=colors, ts=self._now()))
            if wire is None:                 # no live bond, or veiled → nothing sent
                return {"ok": False, "error": "the sky isn't shared right now"}
            peer["inbox_gift"] = wire        # delivered on the peer's next beat
            return {"ok": True}


def room(brain) -> LiveConfluence:
    """The Brain's confluence room, created on first use and cached on the
    Brain instance (the same lifetime pattern as the cached world-lens host —
    erase/restart drops it, and the room holds no durable state anyway)."""
    r = getattr(brain, "_live_confluence", None)
    if r is None:
        r = LiveConfluence(brain)
        brain._live_confluence = r
    return r
