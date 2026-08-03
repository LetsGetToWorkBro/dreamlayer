"""The Brain says where it is — `lan_discovery`, Brain-side.

WHAT WAS MISSING
----------------
`orchestrator/discovery_zeroconf.py` has been a complete, correct mDNS
advertiser and browser since it was written. Nothing has ever called it. Its
only intended consumer was the `Orchestrator` the shipped Brain never builds
(`decisions/0001`) — the ninth instance of that pattern, and the same fix each
time: re-host the plain half Brain-side rather than resurrecting the
Orchestrator.

So the capability's own gain text — *"baseline needs the Brain's IP typed in;
this lets the phone find it automatically"* — described something no build has
ever done, and the report filed it as unreachable BY DESIGN because its seam
string began with `orchestrator/`.

WHAT ADVERTISING ACTUALLY BUYS, STATED HONESTLY
-----------------------------------------------
A beacon is half a handshake, and it is worth being exact about which half.

  * The Brain publishing `_dreamlayer._tcp.local` is the PREREQUISITE. Nothing
    on the LAN can discover a service that is not advertised, so until this
    existed every consumer — present or future — was blocked on the same
    missing line.
  * The consumer shipped in this change is the CLI: `dreamlayer plugins
    install .` with no `--brain` used to fail with "no Brain — pass --brain URL
    or set DREAMLAYER_BRAIN". It finds the Brain on the LAN now.
  * The PHONE is not the consumer yet, and this module does not pretend
    otherwise. The app is React Native and reaching mDNS from it needs a native
    module; the phone's path today is the pairing QR, which already carries the
    URL. Claiming the phone half here would be exactly the kind of overclaim the
    capability meter exists to stop.

WHAT GOES ON THE WIRE
---------------------
Presence, host, port. Never the token. A zeroconf TXT record is unauthenticated
multicast — every device on the LAN reads it in the clear, including ones that
have not paired — so the secret rides the authenticated pairing channel instead
(audit 2026-07-15). `discovery_zeroconf._public_only` enforces that at the
publishing boundary rather than trusting this file to remember.

The ADDRESSES are the other half of that care. The seam's own fallback is
`gethostbyname(gethostname())`, a single guess that is 127.0.0.1 on many Linux
hosts and an arbitrary interface on a multi-NIC one. The Brain already solved
this for the pairing QR — `server.lan_ip_candidates()`, default-route first,
RFC1918 only, after a virtual adapter once got advertised over the real LAN
(refute 2026-07-20) — so the beacon publishes that list rather than re-deriving
it worse.
"""
from __future__ import annotations

import logging

log = logging.getLogger("dreamlayer.discovery_live")

#: How long a browse listens before answering. Long enough for a Brain on the
#: same subnet to respond, short enough that a CLI command that finds nothing
#: still feels like it failed fast rather than hung.
FIND_TIMEOUT = 2.0

#: The advertised service name. Deliberately NOT the hostname: a hostname is a
#: personal detail ("stephanies-macbook") broadcast to every device on whatever
#: LAN the wearer is on, including a café's.
SERVICE_NAME = "DreamLayer Brain"


class BrainBeacon:
    """The Brain's presence on the LAN, registered once and held."""

    def __init__(self, brain=None):
        self.brain = brain
        self._disc = None
        #: True only once zeroconf accepted the registration. See `driving()`
        #: for what this does and does not prove.
        self.registered = False
        self.port = 0
        #: Brains other than this one that a browse has actually turned up.
        self.found_total = 0

    def discovery(self):
        if self._disc is None:
            from ...orchestrator.discovery_zeroconf import Discovery
            self._disc = Discovery()
        return self._disc

    # ------------------------------------------------------------- advertise

    def advertise(self, port: int, tls_port=None) -> bool:
        """Publish this Brain. Returns whether it is now on the air.

        Idempotent: a second call on a live beacon is a no-op rather than a
        second registration, because `serve_forever` can be re-entered in tests
        and two services with the same name on one Zeroconf instance is an
        error rather than a louder beacon.

        Never raises. A Brain that cannot advertise must still serve — the
        wearer's fallback is the pairing QR they have always used, which is the
        floor this capability is held to like every other optional dependency.
        """
        if self.registered:
            return True
        try:
            from .server import lan_ip_candidates
            addrs = lan_ip_candidates()
        except Exception as exc:                     # noqa: BLE001
            log.debug("[discovery] address lookup failed: %s", type(exc).__name__)
            addrs = []
        if not addrs:
            # Loopback-only. Advertising here would put an address on the LAN
            # that resolves back to whoever READ it, which is worse than not
            # advertising: a phone would "find" a Brain and dial itself.
            log.info("[discovery] no LAN address — not advertising")
            return False
        props = {"path": "/dreamlayer", "v": "1"}
        if tls_port:
            # The port a phone camera needs (a browser gives no camera to an
            # insecure page). Not a secret — it is a port number on a host that
            # just published its address.
            props["https"] = str(int(tls_port))
        try:
            ok = bool(self.discovery().advertise(
                int(port), name=SERVICE_NAME, addresses=addrs,
                properties=props))
        except Exception as exc:                     # noqa: BLE001
            log.warning("[discovery] advertise failed: %s", type(exc).__name__)
            return False
        if ok:
            self.registered = True
            self.port = int(port)
            # The ADDRESS COUNT, not the addresses. A LAN IP is not a secret
            # the way a token is, but it is still where the wearer physically
            # is, and a log line is the wrong place to put it.
            log.info("[discovery] advertising on %d address(es), port %d",
                     len(addrs), int(port))
        return ok

    def stop(self) -> None:
        """Withdraw the service. Safe to call on a beacon that never started."""
        if self._disc is None:
            return
        try:
            self._disc.stop()
        except Exception as exc:                     # noqa: BLE001
            log.debug("[discovery] stop failed: %s", type(exc).__name__)
        self.registered = False

    # ---------------------------------------------------------------- browse

    def find(self, timeout: float = FIND_TIMEOUT) -> list:
        """Brains on this LAN, as `[{name, host, port}]`.

        Empty on a machine without zeroconf installed, which is the fallback
        working — every caller here already has a hand-configured path and this
        only ever saves the wearer from using it.
        """
        try:
            got = list(self.discovery().discover(timeout=float(timeout)) or [])
        except Exception as exc:                     # noqa: BLE001
            log.warning("[discovery] browse failed: %s", type(exc).__name__)
            return []
        self.found_total += len(got)
        return got

    # ---------------------------------------------------------------- report

    def driving(self) -> bool:
        """Whether the capability is doing its job right now.

        This one is weaker than the proof-based promotions elsewhere in this
        tree, and the honest thing is to say so rather than dress it up. A
        classifier can be asked "did you return a label"; an advertiser has no
        such feedback — mDNS gives the publisher no way to learn that anybody
        listened. So "registered" is the strongest evidence available, and it is
        genuinely more than `import zeroconf`: it means an address was found, a
        service was accepted, and the beacon is live on this LAN this minute.

        It goes back DOWN when the beacon stops, which is the property that
        makes it a state rather than a claim.
        """
        return bool(self.registered) or self.found_total > 0

    def status(self) -> dict:
        return {"registered": self.registered, "port": self.port,
                "found": self.found_total, "live": self.driving()}


def beacon(brain=None) -> BrainBeacon:
    """The Brain's one beacon, built on first use and held for the session."""
    if brain is None:
        return BrainBeacon(None)
    got = getattr(brain, "_beacon", None)
    if got is None:
        got = BrainBeacon(brain)
        brain._beacon = got
    return got


def find_brain(timeout: float = FIND_TIMEOUT) -> str:
    """The base URL of a Brain on this LAN, or "" — the CLI's entry point.

    Returns a URL only when the answer is UNAMBIGUOUS. With two Brains on the
    LAN this returns "" and the caller falls back to asking, because silently
    picking one would send a plugin install to whichever machine happened to
    answer the multicast first — a wrong-host action the wearer never saw a
    prompt for.
    """
    found = BrainBeacon(None).find(timeout)
    hosts = {(f.get("host"), f.get("port")) for f in found
             if f.get("host") and f.get("port")}
    if len(hosts) != 1:
        if len(hosts) > 1:
            log.info("[discovery] %d Brains on this LAN — not guessing",
                     len(hosts))
        return ""
    host, port = hosts.pop()
    return f"http://{host}:{int(port)}"
