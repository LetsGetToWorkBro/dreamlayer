"""The wire from the Brain to the glasses.

WHAT WAS MISSING
----------------
Everything except this. The glasses have a complete renderer
(`halo-lua/display/renderer.lua`, the Meridian/Cinema-v2 loop). The Brain has
complete producers — twenty capabilities that a live path drives. And
`bridge/real_bridge.py` speaks BLE to a Halo over `brilliant-ble` +
`brilliant-msg`, with `send_card(payload, event)` sitting there waiting.

The `bridge/` package is constructed in exactly two places: `main.py`'s emulator
helper and `simulator/`. Both hang off the `Orchestrator`, which
`decisions/0001` records the shipped Brain never instantiates. So the transport
was written, tested, and reachable only from code the wearer does not run — the
fourth instance of that pattern this file's neighbours have each fixed
(`retention_live.py`, `ear.py`, `attention_live.py`), and the largest, because
it is the reason nothing at all reached the glass.

`truth_live.py` said so in passing while fixing its own case: *"the phone talks
to the Brain and nothing else, so 'Read the room' … reached the glass only on a
surface that does not exist yet."* This is that surface.

WHY IT IS A SUBSCRIBER AND NOT A CALL SITE
------------------------------------------
The obvious build is to teach each producer to also send to the glasses. That
would be twenty edits, twenty chances to forget, and a permanent second list to
keep in step — the `person_guard` shape this repo keeps centralising away from.

Instead this registers a queue in `Brain._event_subs`, the same list the Live
Lens's SSE stream registers in. `push_event` already fans out to every
subscriber, so **every card that reaches the phone reaches the glasses, and any
future card does too, with no further wiring.** A producer cannot forget to
support the glasses because it never had to know they exist.

It also means the gating is already correct and must not be repeated here. By
the time a card is in that queue it has passed the Veil, the wearer's
interruption preferences, and the learned attention bar. Re-checking any of
them would double-gate; ignoring the `safety` flag would let a smoke alarm be
dropped by a queue policy meant for ambient cards.

FAILURE POSTURE
---------------
A glasses link is a radio to a battery-powered device that walks out of range.
It fails SOFT and in one direction: a bridge that is missing, disconnected,
slow, or throwing must never block `push_event`, never raise into a producer,
and never hold a card back from the phone. The queue is bounded and drops its
oldest ambient card under pressure rather than growing; `push_event`'s own
`put_nowait` already declines to block on a full one.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

log = logging.getLogger("dreamlayer.halo_link")

#: Cards buffered for the glasses before the oldest ambient one is dropped. A
#: radio link is slower than an SSE socket, so this is the shock absorber
#: between a burst of cards and a device that is mid-frame.
QUEUE_MAX = 32

#: How long a drained card may take to reach the device before the link is
#: considered wedged rather than slow.
SEND_TIMEOUT_S = 5.0

#: Kinds that must survive a full queue, matching `push_event`'s own policy.
#: A safety push evicts an ambient card rather than being dropped.
_SAFETY = "safety"


class HaloLink:
    """One Brain, one pair of glasses, one queue between them."""

    def __init__(self, brain, bridge=None, now_fn=time.time):
        self.brain = brain
        self.bridge = bridge
        self._now = now_fn
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self.connected = False
        self.device: dict = {}
        #: Proof counters. `sent` is what actually reached the device — the
        #: honest measure of this link, and what a status read reports rather
        #: than "a bridge object exists".
        self.sent = 0
        self.dropped = 0
        self.failures = 0
        self.last_error = ""
        self.last_sent_at = 0.0

    # ------------------------------------------------------------- lifecycle

    def connect(self, lua_root: str = "") -> dict:
        """Bring the link up and start forwarding. Idempotent."""
        with self._lock:
            if self.bridge is None:
                return {"ok": False, "reason": "no bridge configured"}
            if self.connected:
                return {"ok": True, **self.status()}
            try:
                self.device = dict(self.bridge.connect() or {})
            except Exception as exc:                 # noqa: BLE001
                self.last_error = type(exc).__name__
                log.warning("[halo] connect failed: %s", type(exc).__name__)
                return {"ok": False, "reason": "connect failed"}
            if lua_root:
                # Best-effort: a Brain that cannot push the Lua bundle can still
                # drive a device already running it, and refusing to connect
                # over a bundle problem would strand a working pair of glasses.
                try:
                    self.bridge.load_lua_app(lua_root)
                except Exception as exc:             # noqa: BLE001
                    log.warning("[halo] lua load failed: %s", type(exc).__name__)
            self.connected = True
            self._stop.clear()
            self._subscribe()
            self._worker = threading.Thread(target=self._drain, daemon=True,
                                            name="halo-link")
            self._worker.start()
            return {"ok": True, **self.status()}

    def disconnect(self) -> dict:
        with self._lock:
            self._stop.set()
            self._unsubscribe()
            self.connected = False
            try:
                if self.bridge is not None:
                    self.bridge.disconnect()
            except Exception as exc:                 # noqa: BLE001
                log.warning("[halo] disconnect: %s", type(exc).__name__)
            # Wake the drain loop so it can observe `_stop` promptly instead of
            # sitting on its get() timeout.
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass
            return {"ok": True, **self.status()}

    def status(self) -> dict:
        return {"connected": self.connected,
                "device": self.device,
                "queued": self._q.qsize(),
                "sent": self.sent,
                "dropped": self.dropped,
                "failures": self.failures,
                "last_error": self.last_error,
                "last_sent_at": self.last_sent_at,
                "driving": self.driving()}

    def driving(self) -> bool:
        """True only once a card has genuinely reached the device.

        Connected is not driving, and a bridge object existing is neither. This
        is what a capability report should follow, for the same reason
        `attention_live.tuning_live()` follows a fitted bar rather than an
        importable library.
        """
        return self.sent > 0

    # ----------------------------------------------------------- the wiring

    def _subscribe(self) -> None:
        """Join `Brain._event_subs` — the same list the Live Lens joins.

        This is the whole design. Nothing else in the Brain learns that glasses
        exist, and every card the phone gets, the glass gets.
        """
        try:
            with self.brain._event_lock:
                if self._q not in self.brain._event_subs:
                    self.brain._event_subs.append(self._q)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[halo] could not subscribe: %s", type(exc).__name__)

    def _unsubscribe(self) -> None:
        try:
            with self.brain._event_lock:
                if self._q in self.brain._event_subs:
                    self.brain._event_subs.remove(self._q)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[halo] could not unsubscribe: %s", type(exc).__name__)

    def _drain(self) -> None:
        while not self._stop.is_set():
            try:
                ev = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if ev is None:                            # the disconnect nudge
                continue
            self._send(ev)

    def _send(self, ev: dict) -> None:
        """One card to the device. Never raises — this runs on the link thread
        and an exception here would silently kill forwarding for the session."""
        if self.bridge is None or not self.connected:
            self.dropped += 1
            return
        try:
            card = ev.get("card") if isinstance(ev, dict) else None
            if not isinstance(card, dict):
                return                                # nothing to draw
            kind = str(ev.get("kind") or "answer_ready")
            self.bridge.send_card(card, kind)
            self.sent += 1
            self.last_sent_at = float(self._now())
        except Exception as exc:                      # noqa: BLE001
            self.failures += 1
            self.last_error = type(exc).__name__
            # Deliberately NOT the card, the kind, or anything off it: a send
            # failure is a transport fact and the card is the wearer's content.
            log.warning("[halo] send failed: %s", type(exc).__name__)


def link(brain) -> HaloLink:
    """The Brain's one link, built on first use and held for the session."""
    got = getattr(brain, "_halo", None)
    if got is None:
        got = HaloLink(brain)
        brain._halo = got
    return got


def build_bridge(kind: str = "emulator"):
    """A bridge by name, or None with the reason logged.

    `emulator` always works and is what the pre-hardware build runs against;
    `real` needs `brilliant-ble`/`brilliant-msg` and an actual pair of glasses
    in range. Both satisfy `bridge/base.BridgeBase`, so nothing above this line
    knows which one it is talking to — which is what makes the emulator a real
    test of the wiring rather than a mock of it.
    """
    try:
        if kind == "real":
            from ...bridge.real_bridge import RealBridge
            return RealBridge()
        from ...bridge.emulator_bridge import EmulatorBridge
        return EmulatorBridge()
    except Exception as exc:                          # noqa: BLE001
        log.warning("[halo] bridge %s unavailable: %s", kind, type(exc).__name__)
        return None
