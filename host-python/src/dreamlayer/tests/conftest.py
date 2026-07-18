"""Suite-wide no-cloud-egress proof (A2).

The privacy claim of a camera-and-mic device is "it stays on your device / your
LAN". Before this, that was only ever checked by an in-process `cloud_calls`
counter — a value the code under test increments itself. A bug that made a real
outbound connection *without* going through the counted path (a stray
`requests.get`, an ML lib phoning a CDN, a telemetry ping) would sail past every
test while the counter still read 0.

This closes that gap at the OS boundary. A process-wide `sys.addaudithook`
watches the raw `socket.connect` event — the chokepoint EVERY higher-level HTTP
client funnels through — and RAISES on any connection to a public address. An
autouse fixture arms it for the whole default suite, so the entire test run is a
standing proof that nothing reaches the cloud. Loopback and the project's own
LAN ranges (the exact `_LOCAL_NETS` the server uses to define "not egress") are
allowed, because the Brain legitimately binds localhost and discovers its LAN IP
(`__main__._lan_ip` connects a UDP socket to an RFC-1918 address).

Belt-and-suspenders: CI also runs a leg under `unshare -n` (an empty network
namespace) so even a hook someone deleted can't make egress succeed. The two are
complementary — the hook localizes *which test* leaked; the namespace proves the
box had no route regardless.

Opt out with `@pytest.mark.allow_egress` (or the `hardware`/`real_model`
markers, which may legitimately reach a device or a model CDN). Focused code can
use the `no_cloud_egress()` context manager directly.
"""
from __future__ import annotations

import contextlib
import ipaddress
import sys

import pytest

# The one definition of "on my device / my LAN" — mirrors
# ai_brain.server.backends._LOCAL_NETS verbatim (loopback, the three RFC-1918
# blocks, IPv4/IPv6 link-local, IPv6 ULA + loopback). Anything outside is a
# public host and therefore egress. Kept as a local copy so this hook, which
# installs at the very start of collection, has no import-order dependency on
# the server package.
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
    if not isinstance(host, str):
        return True
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


# Audit hooks cannot be removed once installed, so the tripwire is armed/disarmed
# through this module-level flag rather than by add/remove. Default disarmed:
# collection, imports, and opted-out tests run without the guard.
_ARMED = False


def _audit(event: str, args: tuple) -> None:
    if not _ARMED or event != "socket.connect":
        return
    address = args[1] if len(args) > 1 else None
    if not _addr_is_local(address):
        raise EgressError(
            f"blocked cloud egress: socket.connect({address!r}). DreamLayer's "
            f"privacy contract is on-device/LAN only — no test should reach a "
            f"public host. If this connection is intentional, mark the test "
            f"@pytest.mark.allow_egress (and justify it); otherwise it is the "
            f"leak this harness exists to catch.")


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


@pytest.fixture(autouse=True)
def _no_cloud_egress(request):
    """Arm the no-egress proof for every default-suite test. A test that must
    reach the network opts out via @pytest.mark.allow_egress / hardware /
    real_model (all deselected in the default CI job)."""
    if any(request.node.get_closest_marker(m) for m in _OPT_OUT_MARKERS):
        yield
        return
    with no_cloud_egress():
        yield
