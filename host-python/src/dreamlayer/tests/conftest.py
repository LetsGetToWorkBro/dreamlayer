"""Suite-wide no-cloud-egress proof (A2).

The privacy claim of a camera-and-mic device is "it stays on your device / your
LAN". Before this, that was only ever checked by an in-process `cloud_calls`
counter — a value the code under test increments itself. A bug that made a real
outbound connection *without* going through the counted path (a stray
`requests.get`, an ML lib phoning a CDN, a telemetry ping) would sail past every
test while the counter still read 0.

This closes that gap at the OS boundary. A process-wide `sys.addaudithook`
watches the raw `socket.connect`/`socket.sendto`/`socket.sendmsg` events — the
chokepoints TCP and connectionless-UDP egress funnel through — and RAISES on any
send to a public address. It is armed from the moment this conftest is imported
(so collection, imports, and session/module-scoped fixtures are covered too, not
only function bodies); the autouse fixture merely DISARMS it for opted-out tests.
So the entire default run is a standing proof that nothing reaches the cloud.
Loopback and the project's own LAN ranges are allowed, because the Brain
legitimately binds localhost and discovers its LAN IP (`__main__._lan_ip`
connects a UDP socket to an RFC-1918 address).

Belt-and-suspenders: CI also runs the network-sensitive tests under `unshare -rn`
(an empty network namespace with only loopback up) so even a hook someone deleted
can't make egress succeed — the box has no route off-device. The two are
complementary — the hook localizes *which test* leaked; the namespace proves the
environment itself cannot leak.

Opt out with `@pytest.mark.allow_egress` (or the `hardware`/`real_model`
markers, which may legitimately reach a device or a model CDN). Focused code can
use the `no_cloud_egress()` context manager directly.
"""
from __future__ import annotations

import contextlib
import ipaddress
import sys

import pytest

# "On my device / my LAN": the server's ai_brain.server.backends._LOCAL_NETS
# (loopback + the three RFC-1918 blocks + IPv4 link-local + ::1), EXTENDED with
# IPv6 link-local (fe80::/10) and ULA (fc00::/7) — which are likewise not routable
# off the LAN and so are not cloud egress. Anything outside is a public host and
# therefore egress. Kept as a local copy (not imported) so this hook, which
# installs at the very start of collection, has no import-order dependency on the
# server package; the two are cross-checked by a test, not shared by reference.
_ALLOWED_NETS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "::1/128", "fe80::/10", "fc00::/7"))


class EgressError(RuntimeError):
    """A test attempted a network connection to a public (non-LAN) address."""


def _addr_is_local(address) -> bool:
    """True when a `socket.connect` target is loopback/LAN (i.e. NOT egress).

    Fail-safe: a target we cannot positively classify as local — a bare
    hostname, an unparseable address — is treated as egress, because
    under-counting a call that actually left the device is the privacy lie we
    are guarding against. AF_UNIX (a filesystem path, not a tuple) never leaves
    the machine and is always local.
    """
    if not isinstance(address, tuple) or not address:
        return True                          # AF_UNIX path / unknown non-inet
    host = address[0]
    # a BYTES host in an inet tuple — socket.connect((b"8.8.8.8", 80)) — is real
    # egress; decode before the check. Anything still not a str inside an inet
    # tuple is unclassifiable → egress (fail-safe), NOT local (refute 2026-07-21).
    if isinstance(host, (bytes, bytearray)):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    host = host.strip().lower()
    if host in ("", "localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False                         # a hostname → treat as egress
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:                    # ::ffff:127.0.0.1 → classify the v4
        ip = mapped
    return any(ip in net for net in _ALLOWED_NETS)


# The egress chokepoints we watch. TCP funnels through socket.connect, but an
# UNCONNECTED UDP socket egresses via sendto/sendmsg WITHOUT ever calling connect
# (QUIC/HTTP-3, DNS-over-UDP, trivial exfil) — watching only connect missed those
# (refute 2026-07-18). All three carry the target address at args[1].
_EGRESS_EVENTS = frozenset({"socket.connect", "socket.sendto", "socket.sendmsg"})

# Audit hooks cannot be removed once installed, so the tripwire is armed/disarmed
# through this module-level flag. ARMED BY DEFAULT from the moment conftest is
# imported, so collection, imports, and session/module-scoped fixtures are covered
# too (refute 2026-07-18: a function-scoped autouse arm left all of those un-armed);
# the autouse fixture only DISARMS for opted-out tests.
_ARMED = True


def _audit(event: str, args: tuple) -> None:
    if not _ARMED or event not in _EGRESS_EVENTS:
        return
    address = args[1] if len(args) > 1 else None
    if not _addr_is_local(address):
        raise EgressError(
            f"blocked cloud egress: {event}({address!r}). DreamLayer's privacy "
            f"contract is on-device/LAN only — no test should reach a public host. "
            f"If this connection is intentional, mark the test "
            f"@pytest.mark.allow_egress (and justify it); otherwise it is the leak "
            f"this harness exists to catch.")


sys.addaudithook(_audit)


@contextlib.contextmanager
def no_cloud_egress():
    """Arm the egress tripwire for a block of code (nestable)."""
    global _ARMED
    prev = _ARMED
    _ARMED = True
    try:
        yield
    finally:
        _ARMED = prev


_OPT_OUT_MARKERS = ("allow_egress", "hardware", "real_model")


@contextlib.contextmanager
def _disarmed():
    global _ARMED
    prev = _ARMED
    _ARMED = False
    try:
        yield
    finally:
        _ARMED = prev


@pytest.fixture(autouse=True)
def _no_cloud_egress(request):
    """The guard is armed by default (module import); this fixture only DISARMS
    for a test that must reach the network — @pytest.mark.allow_egress / hardware
    / real_model (all deselected in the default CI job). Note the default job's
    marker filter also deselects allow_egress, so an opted-out test never runs in
    the 'green ⇒ zero egress' suite."""
    if any(request.node.get_closest_marker(m) for m in _OPT_OUT_MARKERS):
        with _disarmed():
            yield
    else:
        with no_cloud_egress():          # armed (idempotent) for the test body
            yield

# ---------------------------------------------------------------------------
# The face-embedding test double.
# ---------------------------------------------------------------------------
# `truth_lens.face_embed.FaceEmbedder` FAILS CLOSED in production: with no real
# model wired it declines rather than fabricate an identity (it used to seed a
# 512-d gaussian from the frame's PIXEL SUM, which named strangers as contacts at
# "100% match" roughly once every 43,800 frame pairs). The suite still needs *an*
# embedder to exercise introductions, notes, the dossier and recall, so every
# test runs against the documented double in that module: it recalls a
# byte-identical frame and never confuses two different ones.
#
# This is autouse and suite-wide ON PURPOSE. Wiring it here rather than in
# production means a test can never accidentally prove that the shipped build
# recognises faces -- `test_stack_audit_lenses.py` opts out explicitly to assert
# the production path declines.

@pytest.fixture(autouse=True)
def _face_embedder_double(request, monkeypatch):
    # A test that opted OUT of the double is asserting what the SHIPPED DEFAULT
    # build does — "the production embedder declines rather than guess". Since a
    # real model now exists behind the opt-in `face` extra, a developer who
    # installed it locally would otherwise flip those assertions on their
    # machine and nowhere else: the suite would start claiming the default build
    # recognises faces, which is the one thing this fixture's comment says must
    # never happen. So opting out of the double ALSO pins the backend to absent,
    # and the default gate says the same thing on every machine.
    #
    # `real_model` tests are the deliberate exception: those exist to run the
    # actual weights, and they carry both marks.
    if "no_face_double" in request.keywords:
        if "real_model" not in request.keywords:
            from dreamlayer.truth_lens import face_backends as fb
            # Only the RESOLUTION is stubbed, not `available()`: tests that
            # probe the backend's own dependency/weights logic must still see
            # the real function, or they would pass vacuously.
            monkeypatch.setattr(fb, "default_face_embed_fn", lambda: None)
        return
    from dreamlayer.truth_lens import face_embed as fe
    real_init = fe.FaceEmbedder.__init__

    def _init(self, threshold=fe.DETECTION_THRESHOLD, embed_fn=None):
        real_init(self, threshold,
                  embed_fn or fe.deterministic_embed_fn(max(threshold, 0.9)))

    monkeypatch.setattr(fe.FaceEmbedder, "__init__", _init)
