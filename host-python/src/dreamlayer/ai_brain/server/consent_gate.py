"""Nothing consequential happens without the wearer having said so — the gate.

WHY THIS EXISTS
---------------
This product's answer to a hard feature is CONSENT, not refusal. It will run
face recognition, voice recognition and a third-party lookup — the capability is
the point — and the wearer decides, per thing, knowing what it does. What was
missing was somewhere to decide from: the switches existed in a dozen places
with a dozen names (`cloud_enabled`, `no_cloud`, `network_mode`, a remote
`api_base_url`, a Meshtastic host, `face_recognition`), and a wearer who wanted
to answer *"what is this device doing, and to whom?"* had to read the source.

That is the gap this closes. One registry of every consequential thing, one
predicate each consults, one counter per entry, and one place the panel can
render the whole picture.

WHO IS CONSENTING, AND TO WHAT
------------------------------
The wearer consents on their own behalf. For anything that touches OTHER people
— a face matched, a voice identified — the wearer is also the one who owes those
people a conversation, and this file cannot have it for them. What it can do is
make sure the wearer is never surprised by what their own device is doing, which
is the honest half of the problem and the half that is ours.

IT SURFACES; IT DOES NOT SILENTLY RE-CONSENT
--------------------------------------------
Every sink here names the switch the wearer ALREADY used to turn it on, and this
gate reads that switch rather than inventing a second one. Wrapping a working
cloud tier in a fresh default-deny would break installs that consented long ago
— punishing the honest case to make a diagram tidier.

The default-deny bite is reserved for sinks with NO existing switch of their
own. For those, `allowed()` is False until the wearer grants it, and the grant
is recorded in `config.egress_granted`.

SCOPE IS PART OF THE ANSWER
---------------------------
"Consequential" is not one thing, and collapsing it would make the surface
useless — a wearer who sees their own Home Assistant listed next to a public API
learns nothing. Four scopes, ordered by reach:

    on_device  never leaves, and still about somebody — a face, a voiceprint
    lan        another machine the wearer owns, on their own network
    radio      a broadcast nobody can authenticate — anyone in range hears it
    internet   a third party, off the wearer's network entirely

`radio` sits where it does deliberately: a LoRa mesh does not reach the
internet, but it is heard by strangers, which `lan` is not. And `on_device`
leads rather than trails, because it is the one people forget: a voiceprint of
your colleague never leaves your Mac and is still a biometric of your colleague.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("dreamlayer.egress_consent")

ON_DEVICE = "on_device"
LAN = "lan"
RADIO = "radio"
INTERNET = "internet"


@dataclass(frozen=True)
class Sink:
    """One way data can leave, described the way a wearer would need it.

    `what` and `where` are shown verbatim on the panel, so they are written for
    a person deciding, not for a developer grepping — "one word from a redacted
    transcript" rather than "str".
    """
    key: str
    what: str
    where: str
    scope: str
    #: The `BrainConfig` field the wearer already used to switch this on. None
    #: means the sink has no switch of its own and needs an explicit grant.
    switch: Optional[str] = None
    #: Extra runtime condition, evaluated against the Brain. Used where a
    #: boolean field is not the whole story — the API tier only egresses when
    #: its endpoint is REMOTE, and a local one is not egress at all.
    predicate: Optional[str] = None


#: Every sink that can put wearer data somewhere else. Adding a sink here is
#: how it becomes visible; `test_egress_consent.py` fails if an egress path
#: exists in the tree without an entry, because a gate nobody registered with
#: is a gate that is not doing anything.
SINKS = {
    s.key: s for s in (
        Sink("cloud_ask",
             what="your question, and the memory excerpts used to answer it",
             where="the cloud provider you configured",
             scope=INTERNET, switch="cloud_enabled"),
        Sink("api_brain",
             what="your question, and the memory excerpts used to answer it",
             where="the API endpoint you plugged in",
             scope=INTERNET, predicate="api_is_remote"),
        # NO switch, so this needs an explicit grant, and both halves of that
        # are deliberate. `mesh_tcp_host` is blank for a radio on USB, so
        # keying consent to it would silence exactly the common setup. And
        # plugging a radio in is not consent to TRANSMIT: LoRa is an
        # unauthenticated broadcast heard by everyone in range, which is the
        # one thing in this registry that deserves a separate yes.
        Sink("mesh",
             what="a short line you typed, and nothing the Brain knows",
             where="every Meshtastic radio in range — unencrypted broadcast",
             scope=RADIO),
        Sink("home_assistant",
             what="nothing outbound — it only reads your entity states",
             where="your Home Assistant, on your own network",
             scope=LAN, switch="home_assistant_url"),
        # Registered the moment #602 landed and `lexicon_enabled` existed. It
        # was held back until then because a switch name that does not resolve
        # fails OPEN in the worst way — `getattr` returns None, the sink reads
        # as never-consented, and the feature stops with nothing to point at.
        # `test_every_named_switch_is_a_real_config_field` caught that on the
        # first attempt, which is the whole reason it exists.
        Sink("lexicon",
             what="one rare word, taken from a PII-redacted transcript",
             where="api.dictionaryapi.dev, a keyless third-party dictionary",
             scope=INTERNET, switch="lexicon_enabled"),
        # Nothing below leaves the machine, and every one of them is about a
        # person who is not the wearer. They are listed for exactly that
        # reason: "it stays local" answers a different question from "whose
        # face is in it", and only the first one was ever visible.
        Sink("face_recognition",
             what="a face embedding, matched against people you enrolled",
             where="nowhere — it stays in this Brain's store",
             scope=ON_DEVICE, switch="face_recognition"),
        Sink("face_auto_enrol",
             what="a NEW face added to your people, without asking each time",
             where="nowhere — it stays in this Brain's store",
             scope=ON_DEVICE, switch="face_auto_enrol"),
        Sink("voice_recognition",
             what="a voiceprint, matched against people you enrolled",
             where="nowhere — it stays in this Brain's store",
             scope=ON_DEVICE, switch="voice_recognition"),
        Sink("voice_auto_enrol",
             what="a NEW voiceprint added to your people, without asking",
             where="nowhere — it stays in this Brain's store",
             scope=ON_DEVICE, switch="voice_auto_enrol"),
    )
}


class EgressConsent:
    """The one predicate every sink asks before sending."""

    def __init__(self, brain):
        self.brain = brain
        self._lock = threading.RLock()
        #: Sends that actually happened, per sink. The ledger the panel shows —
        #: "allowed" is a setting, "sent" is a fact, and a wearer auditing their
        #: own device needs the second one.
        self.sent: dict = {}
        #: Sinks that wanted to send and were refused. Surfaced so a feature
        #: that quietly does nothing is legible instead of looking broken.
        self.refused: dict = {}

    # --------------------------------------------------------------- the gate

    def allowed(self, key: str) -> bool:
        """Whether `key` may send right now. Fails CLOSED on anything unknown.

        An unregistered key is a programming error — a new egress path that
        nobody described — and the safe reading of "I do not know what this
        sends or where" is no.
        """
        sink = SINKS.get(key)
        if sink is None:
            # Via `extra`, not the message string. The scanner in
            # `test_logging_discipline.py` cannot tell a sink NAME from a
            # secret named `key`, and it is right not to try — the redaction
            # seam is `extra={...}` and nothing else.
            log.error("[consent] refusing an unregistered sink",
                      extra={"sink": str(key)})
            return False
        # The Veil outranks every grant. Incognito is the wearer saying the
        # Brain is not acting for them right now, and a standing consent is not
        # consent to act during a moment they explicitly closed.
        try:
            if self.brain.incognito_now():
                return False
        except Exception:                            # noqa: BLE001 — unreadable
            return False                             # posture → veiled
        if sink.switch is not None:
            return self._switch_on(sink)
        if sink.predicate is not None:
            return self._predicate(sink)
        return key in set(getattr(self.brain.config, "egress_granted", ()) or ())

    def _switch_on(self, sink: Sink) -> bool:
        """The wearer's EXISTING switch for this sink.

        A string field counts as on when it is non-empty: `mesh_tcp_host` and
        `home_assistant_url` are consent expressed by configuring a destination,
        which is a stronger signal than a checkbox — nobody types their own
        Home Assistant address by accident.
        """
        # Narrowed for the type checker AND as a real guard: this is only
        # reached when `switch` is set, and a None here would silently read the
        # attribute called "None" and answer "never consented" forever.
        if sink.switch is None:
            return False
        got = getattr(self.brain.config, sink.switch, None)
        if isinstance(got, str):
            return bool(got.strip())
        return bool(got)

    def _predicate(self, sink: Sink) -> bool:
        if sink.predicate == "api_is_remote":
            # A LOCAL endpoint is not egress. The Brain already draws this line
            # for the answer tier (`is_local_endpoint`), and drawing it
            # differently here would make the panel disagree with the behaviour.
            try:
                from .backends import is_local_endpoint
                base = (self.brain.config.api_base_url or "").strip()
                return bool(base) and not is_local_endpoint(base)
            except Exception:                        # noqa: BLE001
                return False
        return False

    # ------------------------------------------------------------- the ledger

    def note(self, key: str, n: int = 1) -> None:
        """Record that `key` actually sent. Called AFTER a successful send."""
        with self._lock:
            self.sent[key] = int(self.sent.get(key, 0)) + int(n)

    def note_refused(self, key: str) -> None:
        with self._lock:
            self.refused[key] = int(self.refused.get(key, 0)) + 1

    def check(self, key: str) -> bool:
        """`allowed`, with the refusal counted. The call site sinks should use."""
        if self.allowed(key):
            return True
        self.note_refused(key)
        return False

    # ---------------------------------------------------------------- grants

    def grant(self, key: str) -> bool:
        """Consent to a sink that has no switch of its own."""
        if key not in SINKS:
            return False
        got = set(getattr(self.brain.config, "egress_granted", ()) or ())
        got.add(key)
        self.brain.config.egress_granted = sorted(got)
        self.brain.save()
        return True

    def revoke(self, key: str) -> bool:
        got = set(getattr(self.brain.config, "egress_granted", ()) or ())
        got.discard(key)
        self.brain.config.egress_granted = sorted(got)
        self.brain.save()
        return True

    # ---------------------------------------------------------------- report

    def report(self) -> list:
        """Every sink, what it sends, where, whether it may, and whether it has.

        Sorted with the furthest-reaching first: a wearer scanning this should
        meet the internet sinks before the ones that never leave their house.
        """
        order = {INTERNET: 0, RADIO: 1, LAN: 2, ON_DEVICE: 3}
        rows = []
        for s in SINKS.values():
            rows.append({"key": s.key, "what": s.what, "where": s.where,
                         "scope": s.scope, "allowed": self.allowed(s.key),
                         "needs_grant": s.switch is None and s.predicate is None,
                         "sent": int(self.sent.get(s.key, 0)),
                         "refused": int(self.refused.get(s.key, 0))})
        rows.sort(key=lambda r: (order.get(str(r["scope"]), 9), str(r["key"])))
        return rows

    def anything_left(self) -> bool:
        """Whether anything has left the DEVICE. `on_device` entries are
        excluded deliberately — a face matched locally is consequential and is
        not egress, and folding the two together would make this answer to
        "has my device talked to anything?" useless."""
        return any(n > 0 for k, n in self.sent.items()
                   if SINKS.get(k) and SINKS[k].scope != ON_DEVICE)


def consent(brain) -> EgressConsent:
    got = getattr(brain, "_egress_consent", None)
    if got is None:
        got = EgressConsent(brain)
        brain._egress_consent = got
    return got
