"""privacy/egress_seal.py — a runtime "nothing left the device" seal (#3).

The CI harness (tests/conftest.py) proves the *test environment* can't leak: a
process-wide `socket.connect`/`sendto`/`sendmsg` audit hook, plus `unshare -n`.
This is its production counterpart — a seal you wrap around a *specific
operation* (a recall, an on-device inference, a dream render) so the Brain can
attest, per operation, that it attempted no cloud egress. The verdict is a small
dict you fold into the SIGNED activity ledger (`activity.add`), so
"nothing left the device for this" becomes a tamper-evident, third-party
checkable receipt — not a promise.

Honesty about the name: this is NOT a zero-knowledge SNARK, and it can't be —
you cannot prove a *negative* about I/O with a succinct proof over a ledger. What
it is, is a real OS-level tripwire: `sys.addaudithook` sees the raw socket
egress chokepoints before a packet leaves, classifies the target as
loopback/LAN vs public, and (in enforce mode) refuses the public ones. The
existing Ed25519 hash-chained ledger already gives tamper-evident, selective
disclosure of individual records, so the seal's verdict inherits that when logged.

Scope: the seal is THREAD-scoped by default (the threaded Brain server runs many
requests at once; a process-global arm would flag one thread's legitimate LAN
call because another thread is sealed). It watches the sealing thread — the one
running the operation you're attesting. LIMITATION (be honest): a thread-scoped
seal does NOT see egress on a thread the operation spawns (a ThreadPoolExecutor,
`loop.run_in_executor`, a bare Thread) — that socket op runs on another thread
with no seal. So when the work may hand off to a pool, seal `whole_process=True`.
`sealed_attest()` — the helper that writes a SIGNED receipt — always uses
whole-process for exactly this reason: it must never certify "clean" while data
left on a worker thread.
"""
from __future__ import annotations

import contextlib
import ipaddress
import sys
import threading
from typing import List, Optional, Tuple

# "On my device / my LAN" — the SAME set the CI harness and the server's
# backends._LOCAL_NETS use (loopback + RFC-1918 + link-local v4/v6 + IPv6 ULA);
# anything else is a public host and therefore egress. Kept as a local copy so
# this module has no import-order dependency; a test cross-checks it against the
# server's constant so the two can't drift.
_ALLOWED_NETS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "::1/128", "fe80::/10", "fc00::/7"))

# TCP funnels through connect(), but an UNCONNECTED UDP socket egresses via
# sendto/sendmsg without ever calling connect (QUIC/HTTP-3, DNS-over-UDP, trivial
# exfil) — so all three are watched. The target address is at args[1].
_EGRESS_EVENTS = frozenset({"socket.connect", "socket.sendto", "socket.sendmsg"})


class EgressAttempt(RuntimeError):
    """A sealed operation attempted a connection to a public (non-LAN) host."""


def _addr_is_local(address) -> bool:
    """True when a socket target is loopback/LAN (NOT egress). Fail-safe: a target
    we can't positively classify as local — a bare hostname, an unparseable
    address — is treated as egress, because under-counting a call that actually
    left is the lie we're guarding against. AF_UNIX (a path) never leaves the
    machine and is always local."""
    if not isinstance(address, tuple) or not address:
        return True                          # AF_UNIX path / unknown non-inet
    host = address[0]
    # CPython accepts a BYTES host in an inet tuple (the `et#`/idna arg form), so
    # `socket.connect((b"8.8.8.8", 80))` is real egress — decode it before the
    # check (refute 2026-07-21). Anything still not a str inside an inet tuple is
    # unclassifiable → treat as egress (fail-safe), NOT local.
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
    if mapped is not None:                    # ::ffff:8.8.8.8 → classify the v4
        ip = mapped
    return any(ip in net for net in _ALLOWED_NETS)


# --- the singleton audit hook -------------------------------------------------
# Audit hooks can't be removed once installed, so the hook is installed ONCE,
# lazily (on the first seal), and is inert unless a seal is active on the calling
# thread. Per-thread active seals live on this thread-local stack; a process-wide
# seal registers here so the hook sees it from every thread.
_local = threading.local()
_process_seals: "List[_Seal]" = []
_process_lock = threading.Lock()
_installed = False
_install_lock = threading.Lock()


def _active_seals() -> "List[_Seal]":
    seals = list(getattr(_local, "seals", ()))
    if _process_seals:
        with _process_lock:
            seals = seals + list(_process_seals)
    return seals


def _audit(event: str, args: tuple) -> None:
    if event not in _EGRESS_EVENTS:
        return
    seals = _active_seals()
    if not seals:
        return
    address = args[1] if len(args) > 1 else None
    if _addr_is_local(address):
        return
    host = address[0] if isinstance(address, tuple) and address else address
    for s in seals:
        s._record(str(host))
    # enforce mode raises BEFORE the packet leaves; observe mode only records.
    if any(s.enforce for s in seals):
        raise EgressAttempt(
            f"egress seal tripped: {event}({address!r}) targets a public host. "
            f"This operation is sealed on-device/LAN-only.")


def _ensure_installed() -> None:
    global _installed
    if _installed:
        return
    with _install_lock:
        if not _installed:
            sys.addaudithook(_audit)
            _installed = True


class _Seal:
    __slots__ = ("enforce", "whole_process", "attempts", "_lock")

    def __init__(self, enforce: bool, whole_process: bool):
        self.enforce = enforce
        self.whole_process = whole_process
        self.attempts: List[str] = []
        self._lock = threading.Lock()

    def _record(self, host: str) -> None:
        with self._lock:
            self.attempts.append(host)

    def verdict(self) -> dict:
        """The attestation to log: sealed (no public attempt), how many were seen,
        and the DISTINCT hosts (so a receipt names what was blocked, without a
        flood). Enforce mode means `sealed` implies nothing left; observe mode
        means `sealed` implies nothing was even attempted."""
        with self._lock:
            hosts = list(dict.fromkeys(self.attempts))
        return {"kind": "egress_seal",
                "sealed": not self.attempts,
                "mode": "enforce" if self.enforce else "observe",
                "attempts": len(self.attempts),
                "hosts": hosts[:16]}


@contextlib.contextmanager
def egress_seal(enforce: bool = True, whole_process: bool = False):
    """Seal a block of code so any attempt to reach a public host is caught.

    enforce=True raises :class:`EgressAttempt` at the OS chokepoint (the packet
    never leaves); enforce=False (observe) records the attempt and lets it
    proceed — useful for auditing without changing behaviour. Yields the `_Seal`;
    read `.verdict()` after the block for the receipt to log. Nestable and
    thread-safe.
    """
    _ensure_installed()
    seal = _Seal(enforce=enforce, whole_process=whole_process)
    if whole_process:
        with _process_lock:
            _process_seals.append(seal)
    else:
        stack = getattr(_local, "seals", None)
        if stack is None:
            stack = _local.seals = []
        stack.append(seal)
    try:
        yield seal
    finally:
        if whole_process:
            with _process_lock:
                with contextlib.suppress(ValueError):
                    _process_seals.remove(seal)
        else:
            with contextlib.suppress(ValueError, AttributeError):
                _local.seals.remove(seal)


def sealed_attest(activity, enforce: bool = False):
    """Convenience: run nothing, just return a context manager that — on exit —
    writes the seal's verdict into a SIGNED ActivityLog so the receipt is
    tamper-evident. Use as::

        with sealed_attest(brain.activity) as seal:
            answer = brain.recall(query)     # sealed: no cloud egress
        # a signed 'egress_seal' record now attests it

    `activity` is any object with `.add(kind, text)` (the Brain's ActivityLog).
    Best-effort logging — a ledger write must never break the sealed work.

    WHOLE-PROCESS on purpose (refute 2026-07-21): a thread-scoped seal watches
    only the calling thread, so an operation that hands its network I/O to a
    worker thread / ThreadPoolExecutor / asyncio executor would egress UNSEEN and
    this would sign a FALSE "nothing left the device" receipt. The attestation
    therefore seals the whole process for its window — a false NEGATIVE (certify
    clean while data left) is the dangerous failure; catching a concurrent,
    possibly-unrelated egress instead is the safe one. It defaults to OBSERVE
    (enforce=False) so it records the truth into the receipt without raising into
    — and breaking — either the sealed work or a concurrent request. Pass
    enforce=True only on a single-purpose Brain where hard-blocking is wanted.
    """
    @contextlib.contextmanager
    def _cm():
        with egress_seal(enforce=enforce, whole_process=True) as seal:
            try:
                yield seal
            finally:
                v = seal.verdict()
                text = ("no egress — stayed on device"
                        if v["sealed"]
                        else f"{v['attempts']} public attempt(s): {', '.join(v['hosts'])}")
                try:
                    activity.add("egress_seal", text)
                except Exception:              # noqa: BLE001 — logging never breaks work
                    pass
    return _cm()


def check_local(host: str, port: int = 443) -> bool:
    """Public helper for callers that want to classify a single target the same
    way the seal does (e.g. before opening a connection)."""
    return _addr_is_local((host, int(port)))


# a small, importable copy the cross-check test compares to the server constant
def allowed_networks() -> Tuple:
    return _ALLOWED_NETS


def _reset_for_tests(local_only: bool = True) -> Optional[int]:
    """Test aid: clear any lingering thread/process seals (never touches the
    installed hook, which is permanent by design). Returns nothing meaningful."""
    with contextlib.suppress(AttributeError):
        _local.seals = []
    if not local_only:
        with _process_lock:
            _process_seals.clear()
    return None
