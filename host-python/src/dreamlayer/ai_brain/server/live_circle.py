"""live_circle.py — GhostMode for a room, through the Brain.

`live_confluence.py` plays the honest pre-hardware role for the PAIRWISE bond:
two phones on this Brain's Live Lens exchange their weather through it, over
the real `BondManager`/`EntangledSky` primitives. This is the same role one
level up — a CIRCLE of wearers, over the real `confluence.mesh.MeshManager`.

That manager was written whole: group keys derived from (group_id, code),
HMAC'd packets, replay and stranger rejection, a quiet-member fade, a group
TTL, and a differentially-private summary of the circle's collective feeling.
It was also constructed NOWHERE. `Orchestrator._init_confluence_plugins` sets
`self.mesh = None` with the comment "attached by the app layer when a circle is
formed", and no app layer ever formed one — so GhostMode, a headline of the
product, could not be reached from any surface a wearer has. `MeshEventBus`
(the `event_bus` capability) wraps a MeshManager, which made it unreachable for
the same reason, one layer further out.

WHAT CROSSES, AND WHAT CANNOT
-----------------------------
The mesh's contract is enforced by the mesh, not restated here: only a feeling
crosses — a weather scalar, a palette, a bearing band, a gesture symbol — never
speech, never a coordinate, never a name. Members are anonymous on the wire.
The one thing this file adds is the ROOM: which sessions are in which circle,
and an inbox per member, standing in for the coded-PHY flood the glasses will
use. Nothing here touches disk or the activity ledger, exactly like its
pairwise sibling.

Every packet in and out goes through `MeshEventBus` rather than the manager
directly. That is not decoration: the bus publishes only when the mesh actually
produced something — a veiled `emit()` returns None and nothing is published —
so a subscriber can never see a packet the privacy contract refused to make.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from ...confluence.emitter_pyee import MeshEventBus
from ...confluence.mesh import QUIET_FADE_S, MeshManager

ROOM_MAX = 12             # sessions holding circle state, per Brain
CIRCLE_MAX = 8            # members in one circle
SESSION_STALE_S = 60.0    # silent this long → dropped from the room
CODE_TTL_S = 600.0        # an unjoined circle code dies after 10 minutes
INBOX_MAX = 32            # wires held for a member between beats


class _PostureGate:
    """The Brain's incognito posture, shaped like the privacy gate the real
    MeshManager expects. Fails CLOSED on an unreadable posture — the veil is
    about the record, and an unknown posture is not permission."""

    def __init__(self, brain) -> None:
        self._brain = brain

    def allow_capture(self) -> bool:
        try:
            return not bool(self._brain.incognito_now())
        except Exception:                            # noqa: BLE001
            return False

    def allow_recall(self) -> bool:
        return self.allow_capture()


class LiveCircle:
    """The per-Brain GhostMode room. Thread-safe; every public method returns
    plain JSON-ready dicts for the live routes."""

    def __init__(self, brain, now_fn=time.time) -> None:
        self._brain = brain
        self._now = now_fn
        self._lock = threading.Lock()
        self._gate = _PostureGate(brain)
        # sid -> {bus, mgr, group, inbox: [wire], seen, heard: int}
        self._sessions: dict = {}
        # group_id -> {code, ts, sids: set}
        self._circles: dict = {}
        self._join_fails: list = []

    # -- internals ---------------------------------------------------------

    def _drop(self, sid: str) -> None:
        s = self._sessions.pop(sid, None)
        if s is None:
            return
        circle = self._circles.get(s.get("group") or "")
        if circle is not None:
            circle["sids"].discard(sid)
            if not circle["sids"]:
                self._circles.pop(s["group"], None)

    def _prune(self) -> None:
        now = self._now()
        for sid in [s for s, v in self._sessions.items()
                    if now - v["seen"] > SESSION_STALE_S]:
            self._drop(sid)
        for gid in [g for g, c in self._circles.items()
                    if not c["sids"] and now - c["ts"] > CODE_TTL_S]:
            self._circles.pop(gid, None)

    def _session(self, sid: str) -> Optional[dict]:
        s = self._sessions.get(sid)
        if s is not None:
            s["seen"] = self._now()
        return s

    def _enrol(self, sid: str, group_id: str, code: str) -> dict:
        """One member: a real MeshManager bound to the circle, wrapped in the
        event bus, with a listener that keeps this session's bookkeeping.

        The listener is the room's own — the bus's whole point is that the mesh
        does not know who is watching, and the room is simply the first watcher.
        """
        mgr = MeshManager(privacy=self._gate, now_fn=self._now)
        mgr.join(group_id, code)
        bus = MeshEventBus(mgr)
        state = {"bus": bus, "mgr": mgr, "group": group_id, "inbox": [],
                 "seen": self._now(), "folded": []}
        # The room's own listener. `folded` is per-BEAT, not a running total: a
        # caller asking "did anyone answer me just now" is asking about this
        # beat, and a cumulative counter answers a question nobody asked.
        bus.on("receive", lambda member, st=state: st["folded"].append(member))
        self._sessions[sid] = state
        return state

    # -- form / join / leave ------------------------------------------------

    def form(self, sid: str) -> dict:
        """Start a circle and get the code to say out loud.

        The same human handshake as a bond, one word longer, because a code
        spoken to a room has more ears on it.
        """
        sid = (sid or "").strip()
        if not sid:
            return {"error": "no session id"}
        with self._lock:
            self._prune()
            if sid not in self._sessions and len(self._sessions) >= ROOM_MAX:
                return {"error": "the room is full"}
            self._drop(sid)                  # re-forming leaves the old circle
            # Mint through a real manager so the group id and code come from
            # the mesh's own `form`, not from a second implementation here.
            minter = MeshManager(privacy=self._gate, now_fn=self._now)
            group_id, code = minter.form()
            self._circles[group_id] = {"code": code, "ts": self._now(),
                                       "sids": set()}
            self._enrol(sid, group_id, code)
            self._circles[group_id]["sids"].add(sid)
            return {"ok": True, "group": group_id, "code": code}

    def join(self, sid: str, group: str, code: str) -> dict:
        """Join the circle you were given the code for."""
        sid = (sid or "").strip()
        group = (group or "").strip()
        code = "-".join((code or "").lower().split()).strip("-")
        if not sid or not code:
            return {"error": "no session id or code"}
        with self._lock:
            self._prune()
            now = self._now()
            # Wrong-code throttle. The three-word space is small and a wrong
            # code answers 200, which the auth limiter never sees — the same
            # hole the pairwise room closed.
            self._join_fails = [t for t in self._join_fails if now - t < 60.0]
            if len(self._join_fails) >= 10:
                return {"error": "too many wrong codes — wait a minute"}
            if sid not in self._sessions and len(self._sessions) >= ROOM_MAX:
                return {"error": "the room is full"}
            if group:
                circle = self._circles.get(group)
                if circle is None or circle["code"] != code:
                    self._join_fails.append(now)
                    return {"error": "no circle matches that code"}
            else:
                # A code alone is enough — nobody says a group id out loud.
                matches = [g for g, c in self._circles.items()
                           if c["code"] == code]
                if len(matches) > 1:
                    return {"error": "that code is ambiguous right now — "
                                     "form a fresh circle"}
                if not matches:
                    self._join_fails.append(now)
                    return {"error": "no circle matches that code"}
                group = matches[0]
                circle = self._circles[group]
            if len(circle["sids"] - {sid}) >= CIRCLE_MAX:
                return {"error": "that circle is full"}
            self._drop(sid)
            self._enrol(sid, group, circle["code"])
            circle["sids"].add(sid)
            return {"ok": True, "group": group, "members": len(circle["sids"])}

    def leave(self, sid: str) -> dict:
        """Leaving is unilateral, which is the mesh's own rule."""
        with self._lock:
            s = self._sessions.get((sid or "").strip())
            if s is not None:
                try:
                    s["mgr"].leave()
                except Exception:                    # noqa: BLE001
                    pass
            self._drop((sid or "").strip())
            return {"ok": True}

    def alias(self, sid: str, member_id: str, name: str) -> dict:
        """Label a pulse locally — "that one is Maya". Stays on this device;
        the mesh never carries a name, and this room never stores one where
        another member could read it."""
        with self._lock:
            s = self._session((sid or "").strip())
            if s is None:
                return {"ok": False, "error": "not in a circle"}
            s["mgr"].alias(str(member_id or ""), str(name or ""))
            return {"ok": True}

    # -- the only traffic ---------------------------------------------------

    def pulse(self, sid: str, kind: str = "weather", body=None,
              epsilon: float = 1.0) -> dict:
        """One beat from one member: send my feeling to the circle, fold in
        everyone else's, and hand back what the glass would show.

        The veil silences the sending half completely — `emit` returns None,
        the bus publishes nothing, and no wire reaches anyone's inbox. Draining
        continues, because being quiet is not the same as being deaf, and the
        mesh's own receive path is recall-gated where it needs to be.
        """
        kind = str(kind or "weather").strip() or "weather"
        body = dict(body or {})
        with self._lock:
            self._prune()
            s = self._session((sid or "").strip())
            if s is None:
                return {"in_circle": False, "members": [], "heard": 0}
            circle = self._circles.get(s["group"]) or {"sids": set()}
            pkt = s["bus"].publish_emit(kind, body)
            if pkt is not None:
                wire = pkt.to_wire()
                for other in circle["sids"]:
                    if other == sid:
                        continue              # the mesh drops self traffic
                    peer = self._sessions.get(other)
                    if peer is None:
                        continue
                    # Bounded: a member who stops beating must not grow an
                    # unbounded queue on everyone else's behalf.
                    peer["inbox"] = (peer["inbox"] + [wire])[-INBOX_MAX:]
            inbox, s["inbox"] = s["inbox"], []
            s["folded"] = []
            for wire in inbox:
                s["bus"].publish_receive(wire)       # forged/replayed → dropped
            mgr = s["mgr"]
            members = [{"member": m.member_id, "name": mgr.name_of(m.member_id),
                        "kind": m.kind, "body": dict(m.body)}
                       for m in mgr.active(QUIET_FADE_S)]
            out = {"in_circle": True, "group": s["group"],
                   "sent": pkt is not None, "heard": len(s["folded"]),
                   "members": members}
            # The circle's collective feeling, with calibrated noise and a
            # per-group ε budget — an EXACT aggregate over three people tells
            # everyone your value the moment it moves. None once the budget is
            # spent, which is a refusal, not an error.
            summary = mgr.dp_group_summary(
                epsilon=epsilon, my_state=body.get("state"))
            if summary is not None:
                out["shared"] = summary
            return out


    def members_live(self) -> int:
        """How many sessions are holding a live circle right now.

        The promotion proof for `event_bus`: pyee importing is not a bus, and a
        `MeshEventBus` is only ever constructed around a MeshManager that has
        joined a circle — which is what nothing in the tree did.
        """
        with self._lock:
            return sum(1 for s in self._sessions.values() if s["mgr"].live())


def room(brain) -> LiveCircle:
    """The Brain's GhostMode room, created on first use and cached on the Brain
    instance — the same lifetime pattern as the confluence room, and it holds
    no durable state either."""
    r = getattr(brain, "_live_circle", None)
    if r is None:
        r = LiveCircle(brain)
        brain._live_circle = r
    return r
