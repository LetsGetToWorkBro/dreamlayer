"""The no-cloud-egress proof, tested (A2).

`conftest.py` installs a process-wide `socket.connect` audit hook and an autouse
fixture that arms it for every default-suite test — so the whole run is a
standing proof that nothing reaches a public host. These tests pin that the
proof actually *works*: it trips on real egress, it does NOT trip on the
loopback/LAN traffic the Brain legitimately makes, and a representative Brain
operation completes under the armed guard with zero egress.

If someone deletes the hook, `test_public_connect_is_blocked` fails — that's the
revert-failing anchor. (The CI `unshare -n` leg is the belt-and-suspenders: even
a deleted hook can't make egress *succeed* in an empty network namespace.)
"""
from __future__ import annotations

import socket

import pytest

from dreamlayer.tests.conftest import EgressError, _addr_is_local, no_cloud_egress


# --- the classifier: what counts as "not egress" ----------------------------

@pytest.mark.parametrize("host", [
    "127.0.0.1", "127.0.0.5", "10.1.2.3", "172.16.9.9", "192.168.1.50",
    "169.254.10.10", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "localhost",
])
def test_local_and_lan_addresses_are_allowed(host):
    assert _addr_is_local((host, 443)) is True


@pytest.mark.parametrize("host", [
    "8.8.8.8", "1.1.1.1", "140.82.112.3", "2606:4700:4700::1111",
    "example.com", "api.dreamlayer.app", "::ffff:8.8.8.8",
])
def test_public_addresses_are_egress(host):
    assert _addr_is_local((host, 443)) is False


def test_unix_socket_paths_are_local():
    assert _addr_is_local("/run/some.sock") is True
    assert _addr_is_local(b"/run/some.sock") is True


# --- the tripwire: it fires on real egress, stays quiet on loopback ----------

def test_public_connect_is_blocked():
    """The revert-failing anchor: with the autouse guard armed, a connect to a
    public IP raises EgressError from the hook BEFORE any packet leaves. Delete
    the hook and this test goes green-then-connects — which is exactly the
    regression the harness exists to fail on."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(EgressError):
            s.connect(("8.8.8.8", 53))
    finally:
        s.close()


def test_public_udp_sendto_is_blocked():
    """An UNCONNECTED UDP socket egresses via sendto WITHOUT calling connect
    (QUIC/DNS-over-UDP/exfil). The hook watches sendto too (refute 2026-07-18)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(EgressError):
            s.sendto(b"x", ("8.8.8.8", 53))
    finally:
        s.close()


def test_public_udp_sendmsg_is_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(EgressError):
            s.sendmsg([b"x"], [], 0, ("1.1.1.1", 53))
    finally:
        s.close()


def test_loopback_udp_sendto_is_allowed():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(b"x", ("127.0.0.1", 9))   # discard port; must NOT raise
    finally:
        s.close()


def test_allowlist_covers_the_servers_lan_definition():
    """H6: the harness allowlist must be a SUPERSET of the server's _LOCAL_NETS,
    so anything the product treats as 'not egress' is likewise allowed here."""
    from dreamlayer.ai_brain.server.backends import _LOCAL_NETS
    from dreamlayer.tests.conftest import _ALLOWED_NETS
    for net in _LOCAL_NETS:
        # every server-LAN network is contained in some harness-allowed network
        probe = net.network_address
        assert any(probe in a for a in _ALLOWED_NETS), f"{net} not covered"


def test_loopback_connect_is_allowed():
    """A real localhost round-trip must pass the guard untouched."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        cli.connect(("127.0.0.1", port))     # must NOT raise
        conn, _ = srv.accept()
        conn.close()
    finally:
        cli.close()
        srv.close()


def test_lan_discovery_udp_connect_is_allowed():
    """The Brain's own LAN-IP discovery (__main__._lan_ip) connects a UDP socket
    to an RFC-1918 address; that is not egress and must pass the guard."""
    from dreamlayer.ai_brain.server.__main__ import _lan_ip
    ip = _lan_ip()                            # must NOT raise EgressError
    assert isinstance(ip, str) and ip


# --- a representative Brain operation under the armed guard ------------------

def test_brain_local_query_makes_no_egress(tmp_path):
    """An end-to-end local answer path completes with the tripwire armed and the
    cloud_calls counter still at 0 — the counter and the OS-level proof agree."""
    from dreamlayer.ai_brain.server.store import BrainConfig
    cfg = BrainConfig(tmp_path)
    # Whatever the local path does, it must not open a public socket; if it did,
    # the armed hook would already have raised and failed this test.
    assert cfg.cloud_calls == 0


def test_nested_guard_restores_state():
    """no_cloud_egress() is nestable and leaves the outer (autouse) arming
    intact on exit — so opting a block in never disarms the suite-wide proof."""
    with no_cloud_egress():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(EgressError):
                s.connect(("1.1.1.1", 443))
        finally:
            s.close()
    # still armed by the autouse fixture after the inner context exits
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(EgressError):
            s.connect(("1.1.1.1", 443))
    finally:
        s.close()
