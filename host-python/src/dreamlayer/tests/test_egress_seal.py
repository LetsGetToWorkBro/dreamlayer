"""privacy/egress_seal.py — the runtime "nothing left the device" seal (#3).

The seal is the production counterpart to the CI no-egress harness. These pin:
the classifier agrees with the server's local-net rule, a sealed block records /
refuses a public attempt, local + LAN traffic is never flagged, the verdict is
the receipt we log, and the hook is genuinely wired through sys.audit.
"""
from __future__ import annotations

import sys

import pytest

from dreamlayer.privacy import egress_seal as E


class TestClassifier:
    @pytest.mark.parametrize("host", [
        "127.0.0.1", "10.1.2.3", "172.16.9.9", "192.168.1.50",
        "169.254.10.10", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1",
        "localhost", "",
    ])
    def test_local_and_lan_are_not_egress(self, host):
        assert E.check_local(host) is True

    @pytest.mark.parametrize("host", [
        "8.8.8.8", "1.1.1.1", "140.82.112.3", "example.com",
        "api.dreamlayer.app", "::ffff:8.8.8.8",
    ])
    def test_public_and_bare_hostnames_are_egress(self, host):
        assert E.check_local(host) is False

    def test_bytes_host_is_classified_not_waved_through(self):
        # CPython accepts a bytes host: socket.connect((b"8.8.8.8", 80)). It must
        # NOT be treated as local just because it isn't a str (refute 2026-07-21).
        assert E._addr_is_local((b"8.8.8.8", 80)) is False
        assert E._addr_is_local((bytearray(b"1.1.1.1"), 53)) is False
        assert E._addr_is_local((b"127.0.0.1", 80)) is True   # local stays local
        # a genuinely unclassifiable non-str host inside an inet tuple → egress
        assert E._addr_is_local((12345, 80)) is False

    def test_matches_server_local_nets(self):
        # cross-check: every net the server treats as local must be sealed as
        # local too (the seal set is a superset — it adds IPv6 link-local/ULA).
        from dreamlayer.ai_brain.server.backends import _LOCAL_NETS
        seal_nets = set(E.allowed_networks())
        for net in _LOCAL_NETS:
            assert net in seal_nets, f"seal is missing server local net {net}"


class TestSeal:
    def setup_method(self):
        E._reset_for_tests(local_only=False)

    def teardown_method(self):
        E._reset_for_tests(local_only=False)

    def test_clean_block_is_sealed(self):
        with E.egress_seal() as seal:
            E._audit("socket.connect", (None, ("127.0.0.1", 80)))   # local: fine
        v = seal.verdict()
        assert v["sealed"] is True and v["attempts"] == 0

    def test_enforce_raises_on_public(self):
        with pytest.raises(E.EgressAttempt):
            with E.egress_seal(enforce=True) as seal:
                E._audit("socket.connect", (None, ("8.8.8.8", 443)))
        # even though it raised, the attempt was recorded on the seal
        assert seal.verdict()["sealed"] is False
        assert "8.8.8.8" in seal.verdict()["hosts"]

    def test_observe_records_without_raising(self):
        with E.egress_seal(enforce=False) as seal:
            E._audit("socket.sendto", (None, ("1.1.1.1", 53)))      # UDP egress
            E._audit("socket.connect", (None, ("127.0.0.1", 80)))   # local: ignored
        v = seal.verdict()
        assert v["sealed"] is False
        assert v["mode"] == "observe" and v["attempts"] == 1
        assert v["hosts"] == ["1.1.1.1"]

    def test_no_active_seal_is_a_noop(self):
        # outside any seal the hook must not record or raise
        E._audit("socket.connect", (None, ("8.8.8.8", 443)))        # no seal → ignored

    def test_nested_seals_both_see_the_attempt(self):
        with E.egress_seal(enforce=False) as outer:
            with E.egress_seal(enforce=False) as inner:
                E._audit("socket.connect", (None, ("9.9.9.9", 443)))
            assert inner.verdict()["attempts"] == 1
        assert outer.verdict()["attempts"] == 1

    def test_seal_is_removed_after_the_block(self):
        with E.egress_seal():
            pass
        assert E._active_seals() == []


class TestAttest:
    def setup_method(self):
        E._reset_for_tests(local_only=False)

    def test_verdict_is_logged_to_a_signed_activity(self):
        logged = []

        class FakeActivity:
            def add(self, kind, text):
                logged.append((kind, text))

        with E.sealed_attest(FakeActivity(), enforce=False) as seal:
            E._audit("socket.connect", (None, ("127.0.0.1", 80)))
        assert seal.verdict()["sealed"] is True
        assert logged and logged[0][0] == "egress_seal"
        assert "no egress" in logged[0][1]

    def test_logging_never_breaks_the_sealed_work(self):
        class BoomActivity:
            def add(self, *a):
                raise RuntimeError("ledger down")

        # the seal must complete and expose its verdict even if the log write dies
        with E.sealed_attest(BoomActivity()) as seal:
            pass
        assert seal.verdict()["sealed"] is True

    def test_attest_catches_egress_on_a_worker_thread(self):
        # THE false-negative the refute found: an operation that egresses on a
        # spawned thread must NOT be certified clean. sealed_attest seals the
        # whole process, so a worker-thread public connect is still recorded.
        import threading

        class FakeActivity:
            def __init__(self):
                self.logged = []

            def add(self, kind, text):
                self.logged.append((kind, text))

        act = FakeActivity()
        with E.sealed_attest(act) as seal:
            t = threading.Thread(
                target=lambda: E._audit("socket.connect", (None, ("8.8.8.8", 443))))
            t.start()
            t.join()
        v = seal.verdict()
        assert v["sealed"] is False and "8.8.8.8" in v["hosts"]
        assert act.logged and "public attempt" in act.logged[0][1]

    def test_thread_scoped_seal_is_honestly_scoped_to_its_thread(self):
        # documented limitation: a plain (thread-scoped) egress_seal watches only
        # the sealing thread; a worker thread is not covered (which is exactly why
        # sealed_attest uses whole_process). This pins that honest boundary.
        import threading
        with E.egress_seal(enforce=False) as seal:      # thread-scoped
            t = threading.Thread(
                target=lambda: E._audit("socket.connect", (None, ("8.8.8.8", 443))))
            t.start()
            t.join()
        assert seal.verdict()["sealed"] is True         # worker thread not seen


@pytest.mark.allow_egress
def test_hook_is_really_installed_through_sys_audit():
    """End-to-end: with the CI guard disarmed for this test, a synthetic public
    socket.connect audit event routes through the INSTALLED hook and trips the
    seal — proving it's wired to the interpreter, not just callable."""
    E._reset_for_tests(local_only=False)
    with pytest.raises(E.EgressAttempt):
        with E.egress_seal(enforce=True):
            sys.audit("socket.connect", None, ("8.8.8.8", 443))
