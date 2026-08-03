"""A few words, carried miles by radio — `mesh_range`, Brain-side.

WHAT WAS MISSING
----------------
`orchestrator/mesh_bridge.py` is a complete Meshtastic adapter — open a local
node over USB serial or TCP to one on the LAN, send a short line, receive texts
off the pubsub bus — with two real bugs already found and fixed in it (a
byte-vs-character truncation that raised on non-ASCII, and a pypubsub weak-ref
that silently unsubscribed the receive half). Nothing constructed it. Its only
intended consumer was the `Orchestrator` the shipped Brain never builds
(`decisions/0001`).

WHY THIS IS A BRAIN↔BRAIN LINK, NOT A CONFLUENCE ONE
-----------------------------------------------------
The obvious-looking home for this was `live_confluence.py`, the Brain-side room
where two Live Lens phones are bonded. It is the wrong place, and the reason is
worth writing down so nobody re-derives it: both phones in that room reach the
SAME Brain, which means they already have connectivity. A LoRa mesh is for when
they do not — two wearers, two Brains, two radios, miles apart and off-grid.

So this sits at the Brain's own edge: a line the wearer types goes out over the
radio, and a line that arrives lands on the glass. No bond state, because the
mesh is not the bond — the radio is a transport that happens to still work when
nothing else does.

WHAT MAY CROSS, AND WHAT MAY NOT
--------------------------------
LoRa is a broadcast radio. Meshtastic has a channel key, but the honest posture
is that anything sent here is heard by anyone in range on that channel, and that
whoever is on the other end is UNAUTHENTICATED — a node ID is not an identity.

  * OUTBOUND is only ever a line the wearer typed and chose to send. Never a
    memory, a transcript, a position or a card. That is `mesh_bridge`'s own
    stated rule and this file is where it becomes enforceable: the send path
    takes text from a request body and nothing else can reach it.
  * The VEIL applies. Incognito means the Brain is not transmitting on the
    wearer's behalf, which is a stronger reading than "stores nothing" and the
    right one for a radio.
  * INBOUND becomes a card and NOTHING ELSE. It is not observed into the ring,
    not written to memory, not given to a lens. An unauthenticated stranger with
    a $6 radio must not be able to put a sentence into the wearer's memory —
    which is exactly what would happen if this called `ingest_utterance`, and it
    is the single most tempting wrong line in this file.
"""
from __future__ import annotations

import logging

log = logging.getLogger("dreamlayer.mesh_live")

#: Longest line accepted for sending. The radio truncates at 230 BYTES itself
#: and does it correctly; this is the earlier, kinder limit so the wearer is
#: told their line is too long instead of silently losing the end of it.
MAX_CHARS = 180

#: Incoming lines are clipped for the glass. A card is a glance, and a peer that
#: floods is the one thing an open radio channel makes easy.
MAX_CARD_CHARS = 120


class MeshLink:
    """The Brain's one radio, opened on first use and held."""

    def __init__(self, brain, bridge=None):
        self.brain = brain
        self._bridge = bridge
        self._built = bridge is not None
        self._wired = False
        #: Lines that genuinely left over the air, and lines that arrived. The
        #: promotion proof — a node that connected is not a node that carried
        #: anything, and on a radio with no peer in range it never will.
        self.sent = 0
        self.received = 0

    # ---------------------------------------------------------------- bridge

    def bridge(self):
        if not self._built:
            self._built = True
            host = (getattr(self.brain.config, "mesh_tcp_host", "") or "").strip()
            try:
                from ...orchestrator.mesh_bridge import default_mesh
                b = default_mesh(host or None)
                if b is not None and b.connect():
                    self._bridge = b
                elif b is not None:
                    # The wheel is installed and no node answered — a radio not
                    # plugged in, or a LAN host that is not there. Worth saying:
                    # silence here is indistinguishable from "nobody messaged
                    # you", which is the failure mode this whole line of work is
                    # about.
                    log.info("[mesh] meshtastic installed but no node opened")
            except Exception as exc:                 # noqa: BLE001
                log.info("[mesh] node unavailable: %s", type(exc).__name__)
                self._bridge = None
        if self._bridge is not None and not self._wired:
            self._wired = True
            try:
                self._bridge.on_text(self._arrived)
            except Exception as exc:                 # noqa: BLE001
                log.info("[mesh] receive wiring failed: %s", type(exc).__name__)
        return self._bridge

    def ready(self) -> bool:
        b = self.bridge()
        return bool(b is not None and getattr(b, "ready", False))

    # ------------------------------------------------------------------ send

    def send(self, text: str) -> dict:
        """One typed line over the radio. Never anything the Brain knows.

        The Veil applies to TRANSMITTING, not just to storing. Incognito is the
        wearer saying the Brain is not acting on their behalf right now, and
        putting their words on an open radio is acting on their behalf about as
        loudly as this product can.
        """
        line = (text or "").strip()
        if not line:
            return {"ok": False, "reason": "empty"}
        if len(line) > MAX_CHARS:
            return {"ok": False, "reason": "too-long", "max": MAX_CHARS}
        # The Veil first, and reported SEPARATELY from consent. Both refuse,
        # and they are not the same thing to a wearer: "you are incognito right
        # now" is a state they can undo in a second, "you have not consented to
        # the radio" is a decision they have not made. Collapsing them into one
        # reason would tell them the wrong thing to go and fix.
        try:
            if self.brain.incognito_now():
                return {"ok": False, "reason": "veiled"}
        except Exception:                            # noqa: BLE001 — fail closed
            return {"ok": False, "reason": "veiled"}
        # Then the one gate every consequential thing consults, so "what is
        # this device doing, and to whom?" has a single answer instead of a
        # dozen switches with different names.
        from .consent_gate import consent
        if not consent(self.brain).check("mesh"):
            return {"ok": False, "reason": "not-consented"}
        b = self.bridge()
        if b is None or not getattr(b, "ready", False):
            return {"ok": False, "reason": "no-node"}
        try:
            got = bool(b.send(line))
        except Exception as exc:                     # noqa: BLE001
            log.warning("[mesh] send failed: %s", type(exc).__name__)
            return {"ok": False, "reason": "radio-error"}
        if got:
            self.sent += 1
            consent(self.brain).note("mesh")         # a fact, not a setting
        return {"ok": got, "reason": "" if got else "radio-refused"}

    # --------------------------------------------------------------- receive

    def _arrived(self, sender: str, text: str) -> None:
        """A line off the mesh. It becomes a CARD, and nothing else.

        Not observed into the ring, not written to memory, not handed to a lens.
        Whoever sent this is unauthenticated — a Meshtastic node ID is not an
        identity — so anything that let it reach the memory store would let a
        stranger in range write the wearer's history. That is the single most
        tempting wrong line in this module.

        Never raises: this runs on meshtastic's pubsub thread, where an
        exception would take the receive bus down for the session.
        """
        try:
            line = (text or "").strip()[:MAX_CARD_CHARS]
            if not line:
                return
            self.received += 1
            from ...hud import cards
            # `sender` is accepted because the bridge passes it, and is
            # deliberately UNUSED. It is a radio node ID, not a person: looking
            # it up against contacts would put a name on the glass that the
            # transport cannot support, and showing the raw ID would be four
            # bytes of hex where a card has room for the message. If a peer
            # needs identifying, they can say who they are in the line.
            self.brain.push_event("mesh", cards.juno_reply(
                line, kind="action"))
        except Exception as exc:                     # noqa: BLE001
            log.warning("[mesh] inbound failed: %s", type(exc).__name__)

    # ---------------------------------------------------------------- report

    def driving(self) -> bool:
        """A line that actually crossed the air, in either direction.

        Not `available` (the wheel), and not `ready` (a node opened): a radio
        with no peer in range connects perfectly and carries nothing, which is
        the normal state of a mesh and not a working link.
        """
        return (self.sent + self.received) > 0

    def status(self) -> dict:
        return {"ready": self.ready(), "sent": self.sent,
                "received": self.received, "live": self.driving()}

    def close(self) -> None:
        b, self._bridge = self._bridge, None
        self._built = False
        self._wired = False
        if b is not None:
            try:
                b.close()
            except Exception:                        # noqa: BLE001
                pass


def link(brain) -> MeshLink:
    got = getattr(brain, "_mesh_link", None)
    if got is None:
        got = MeshLink(brain)
        brain._mesh_link = got
    return got
