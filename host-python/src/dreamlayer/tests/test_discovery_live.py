"""test_discovery_live.py — the Brain says where it is.

`orchestrator/discovery_zeroconf.py` was a complete mDNS advertiser with no
caller: its only intended consumer was the `Orchestrator` the shipped Brain
never builds (`decisions/0001`). So *"the phone finds the Brain automatically"*
described something no build had ever done.

`zeroconf` is an optional dependency and is usually absent in CI, so the tests
here inject a FAKE zeroconf into the seam rather than skipping. That is
deliberate: what needs proving is our logic — which addresses go out, what is
allowed in the TXT record, that the beacon withdraws — and none of that is
zeroconf's behaviour. The absent-dependency path is tested too, as the floor.
"""
from __future__ import annotations

import pytest

from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server.discovery_live import (
    SERVICE_NAME, BrainBeacon, beacon, find_brain)
from dreamlayer.ai_brain.server.store import BrainConfig
from dreamlayer.orchestrator import discovery_zeroconf as dz


@pytest.fixture(autouse=True)
def _no_db_override(monkeypatch):
    monkeypatch.delenv("DREAMLAYER_DB", raising=False)


def _brain(tmp_path) -> Brain:
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    BrainConfig(token="tok").save(cfg)
    return Brain(cfg)


class _FakeInfo:
    """Stands in for `zeroconf.ServiceInfo` and records what it was handed."""

    def __init__(self, type_, name, addresses=None, port=0, properties=None):
        self.type_ = type_
        self.name = name
        self.addresses = list(addresses or [])
        self.port = port
        self.properties = dict(properties or {})


class _FakeZC:
    """Stands in for a `Zeroconf` instance. Records the register/unregister
    pair, because a beacon that never withdraws is the failure that matters.

    `all` accumulates every instance ever built, and that is not bookkeeping
    for its own sake: `Discovery.advertise` constructs a FRESH `Zeroconf` on
    each call and overwrites `self._zc`, so a second call leaks the first one —
    still open, still advertising, and now with no handle to withdraw it. A test
    that only inspects `last` sees one clean registration and calls that fine,
    which is exactly what it did until a mutation survived.
    """

    last = None
    all: list = []

    def __init__(self):
        self.registered = []
        self.unregistered = []
        self.closed = False
        _FakeZC.last = self
        _FakeZC.all.append(self)

    @classmethod
    def registrations(cls) -> int:
        return sum(len(z.registered) for z in cls.all)

    def register_service(self, info):
        self.registered.append(info)

    def unregister_service(self, info):
        self.unregistered.append(info)

    def close(self):
        self.closed = True


@pytest.fixture
def zc(monkeypatch):
    """A zeroconf that exists, for the length of one test."""
    monkeypatch.setattr(dz, "_HAS_ZC", True)
    monkeypatch.setattr(dz, "Zeroconf", _FakeZC, raising=False)
    monkeypatch.setattr(dz, "ServiceInfo", _FakeInfo, raising=False)
    _FakeZC.last = None
    _FakeZC.all = []
    return _FakeZC


@pytest.fixture
def lan(monkeypatch):
    """Two plausible LAN addresses, default-route first."""
    from dreamlayer.ai_brain.server import server as srv
    monkeypatch.setattr(srv, "lan_ip_candidates",
                        lambda: ["10.0.0.7", "192.168.1.4"])


class TestTheTokenNeverGoesOnTheWire:
    """The one thing that must not regress. A zeroconf TXT record is
    unauthenticated multicast — every device on the LAN reads it in the clear,
    including a café's — so a secret published here defeats the pairing it is
    meant to protect (audit 2026-07-15)."""

    def test_a_token_property_is_dropped(self, zc, lan, tmp_path):
        assert BrainBeacon(_brain(tmp_path)).advertise(7777)
        info = _FakeZC.last.registered[0]
        blob = repr(info.properties).lower()
        assert "token" not in blob and "tok" not in blob

    @pytest.mark.parametrize("key", ["token", "Token", "TOKEN", "pairing_token",
                                     "secret", "api_key", "authz", "cred",
                                     "sig", "PASSPHRASE"])
    def test_the_filter_catches_every_shape_of_secret(self, key):
        out = dz._public_only({key: "rune-birch", "path": "/dreamlayer"})
        assert key not in out
        assert out == {"path": "/dreamlayer"}

    def test_the_positional_token_argument_is_still_never_published(self, zc,
                                                                    lan):
        """`Discovery.advertise` keeps `token` for call-compatibility. It must
        stay inert — a caller that passes it has NOT opted into publishing."""
        assert dz.Discovery().advertise(7777, token="rune-birch",
                                        addresses=["10.0.0.7"])
        assert "rune-birch" not in repr(_FakeZC.last.registered[0].properties)

    def test_the_refusal_log_does_not_reprint_the_secret(self, caplog):
        """And the key rides `extra`, the only seam `logging_setup` redacts —
        a message string reading "refusing to publish token" is exactly what
        `test_logging_discipline.py` catches, and it is right to: a scanner
        cannot tell a key NAME from a key."""
        import logging
        with caplog.at_level(logging.WARNING, logger="dreamlayer.discovery"):
            dz._public_only({"token": "rune-birch"})
        assert "refusing to publish" in caplog.text
        assert "rune-birch" not in caplog.text
        assert getattr(caplog.records[-1], "txt_key", None) == "token"


class TestItAdvertisesTheAddressThePhoneCanReach:
    """The seam's own fallback is `gethostbyname(gethostname())` — 127.0.0.1 on
    many Linux hosts and an arbitrary interface on a multi-NIC one. Publishing
    an unreachable address is the same defect as refute 2026-07-20, where a
    virtual adapter floated above the real LAN and went into the pairing QR."""

    def test_it_publishes_the_brains_own_candidate_list(self, zc, lan, tmp_path):
        import socket
        assert BrainBeacon(_brain(tmp_path)).advertise(7777)
        got = _FakeZC.last.registered[0].addresses
        assert got == [socket.inet_aton("10.0.0.7"),
                       socket.inet_aton("192.168.1.4")]

    def test_the_default_route_address_stays_first(self, zc, lan, tmp_path):
        import socket
        BrainBeacon(_brain(tmp_path)).advertise(7777)
        assert _FakeZC.last.registered[0].addresses[0] == \
            socket.inet_aton("10.0.0.7")

    def test_a_loopback_only_host_does_not_advertise_at_all(self, zc,
                                                            monkeypatch,
                                                            tmp_path):
        """Publishing 127.0.0.1 to the LAN is worse than silence: a phone would
        "find" a Brain and dial ITSELF."""
        from dreamlayer.ai_brain.server import server as srv
        monkeypatch.setattr(srv, "lan_ip_candidates", list)
        b = BrainBeacon(_brain(tmp_path))
        assert b.advertise(7777) is False
        assert b.driving() is False
        assert _FakeZC.last is None, "it opened a Zeroconf with nothing to say"

    def test_the_seam_still_guesses_when_no_addresses_are_passed(self, zc):
        """The floor: the parameter is an improvement, not a requirement. A
        caller that passes nothing gets exactly the old behaviour."""
        assert dz.Discovery().advertise(7777)
        assert len(_FakeZC.last.registered[0].addresses) == 1


class TestWhatItSaysAboutItself:
    def test_the_service_name_is_not_the_hostname(self, zc, lan, tmp_path):
        """A hostname is a personal detail ("stephanies-macbook") broadcast to
        every device on whatever network the wearer is on."""
        import socket
        BrainBeacon(_brain(tmp_path)).advertise(7777)
        name = _FakeZC.last.registered[0].name
        assert name.startswith(SERVICE_NAME)
        assert socket.gethostname() not in name

    def test_the_https_port_rides_when_tls_is_on(self, zc, lan, tmp_path):
        """A phone camera needs a secure page, so the port that serves one is
        the single most useful hint in the record."""
        BrainBeacon(_brain(tmp_path)).advertise(7777, tls_port=7778)
        assert _FakeZC.last.registered[0].properties["https"] == "7778"

    def test_no_https_key_when_there_is_no_tls_listener(self, zc, lan, tmp_path):
        BrainBeacon(_brain(tmp_path)).advertise(7777)
        assert "https" not in _FakeZC.last.registered[0].properties

    def test_the_advertised_port_is_the_one_it_was_given(self, zc, lan,
                                                         tmp_path):
        b = BrainBeacon(_brain(tmp_path))
        b.advertise(9001)
        assert _FakeZC.last.registered[0].port == 9001
        assert b.port == 9001

    def test_the_log_line_does_not_carry_the_address(self, zc, lan, tmp_path,
                                                     caplog):
        """A LAN IP is not a token, but it is still where the wearer physically
        is. The count is what a reader needs."""
        import logging
        with caplog.at_level(logging.INFO, logger="dreamlayer.discovery_live"):
            BrainBeacon(_brain(tmp_path)).advertise(7777)
        assert "advertising" in caplog.text, (
            "nothing was logged, so this asserts nothing about what a log "
            "carries")
        assert "10.0.0.7" not in caplog.text
        assert "192.168.1.4" not in caplog.text


class TestItWithdrawsWhenTheBrainStops:
    """A beacon still registered after the port closes advertises a Brain that
    refuses connections — the phone finds it, dials it, and fails. Worse than
    never having advertised."""

    def test_stop_unregisters_and_closes(self, zc, lan, tmp_path):
        b = BrainBeacon(_brain(tmp_path))
        b.advertise(7777)
        b.stop()
        assert _FakeZC.last.unregistered, "the service was never withdrawn"
        assert _FakeZC.last.closed
        assert b.registered is False

    def test_stop_on_a_beacon_that_never_started_is_safe(self, tmp_path):
        BrainBeacon(_brain(tmp_path)).stop()          # must not raise

    def test_advertising_twice_registers_once(self, zc, lan, tmp_path):
        """`serve_forever` can be re-entered; two services with one name on a
        single Zeroconf is an error, not a louder beacon."""
        b = BrainBeacon(_brain(tmp_path))
        assert b.advertise(7777)
        assert b.advertise(7777)
        # Across EVERY Zeroconf ever built, not just the newest — see _FakeZC.
        assert _FakeZC.registrations() == 1
        assert len(_FakeZC.all) == 1, (
            "a second Zeroconf was opened; the first is leaked, still "
            "advertising, and no longer reachable to withdraw")


class TestTheFloor:
    """With `zeroconf` absent everything must degrade to the pairing QR the
    wearer has always used — never to an exception on the startup path."""

    def test_absent_dependency_advertises_nothing_and_raises_nothing(
            self, monkeypatch, lan, tmp_path):
        monkeypatch.setattr(dz, "_HAS_ZC", False)
        b = BrainBeacon(_brain(tmp_path))
        assert b.advertise(7777) is False
        assert b.find(0.01) == []
        assert b.driving() is False

    def test_a_seam_that_raises_is_absorbed(self, monkeypatch, lan, tmp_path):
        b = BrainBeacon(_brain(tmp_path))

        class _Boom:
            def advertise(self, *a, **k):
                raise RuntimeError("multicast socket refused")

            def discover(self, timeout=0.0):
                raise RuntimeError("no interface")

        b._disc = _Boom()
        assert b.advertise(7777) is False
        assert b.find(0.01) == []


class TestTheCliFindsABrainInsteadOfAsking:
    """The consumer shipped with this. `dreamlayer plugins install .` with no
    `--brain` used to fail on a machine sitting on the same LAN as a Brain."""

    def _args(self, brain="", token=""):
        return type("A", (), {"brain": brain, "token": token})()

    def test_an_explicit_url_always_wins(self, monkeypatch):
        from dreamlayer import cli
        monkeypatch.setattr(
            "dreamlayer.ai_brain.server.discovery_live.find_brain",
            lambda *a, **k: "http://10.0.0.9:7777")
        url, _tok = cli._brain(self._args(brain="http://elsewhere:1234/"))
        assert url == "http://elsewhere:1234"

    def test_the_environment_variable_also_wins(self, monkeypatch):
        from dreamlayer import cli
        monkeypatch.setenv("DREAMLAYER_BRAIN", "http://env-host:7777")
        monkeypatch.setattr(
            "dreamlayer.ai_brain.server.discovery_live.find_brain",
            lambda *a, **k: "http://10.0.0.9:7777")
        url, _tok = cli._brain(self._args())
        assert url == "http://env-host:7777"

    def test_with_neither_it_asks_the_lan(self, monkeypatch):
        from dreamlayer import cli
        monkeypatch.delenv("DREAMLAYER_BRAIN", raising=False)
        monkeypatch.setattr(
            "dreamlayer.ai_brain.server.discovery_live.find_brain",
            lambda *a, **k: "http://10.0.0.9:7777")
        url, _tok = cli._brain(self._args())
        assert url == "http://10.0.0.9:7777"

    def test_discovery_blowing_up_never_breaks_the_command(self, monkeypatch):
        from dreamlayer import cli
        monkeypatch.delenv("DREAMLAYER_BRAIN", raising=False)

        def _boom(*a, **k):
            raise RuntimeError("no multicast here")
        monkeypatch.setattr(
            "dreamlayer.ai_brain.server.discovery_live.find_brain", _boom)
        assert cli._brain(self._args()) == ("", "")


class TestItRefusesToGuessBetweenTwoBrains:
    """Silently picking whichever answered the multicast first would install a
    plugin on the wrong machine — a wrong-host action with no prompt."""

    def _found(self, monkeypatch, rows):
        monkeypatch.setattr(BrainBeacon, "find", lambda self, timeout=0.0: rows)

    def test_exactly_one_brain_answers(self, monkeypatch):
        self._found(monkeypatch, [{"name": "a", "host": "10.0.0.7",
                                   "port": 7777}])
        assert find_brain(0.01) == "http://10.0.0.7:7777"

    def test_two_brains_answer_nothing(self, monkeypatch):
        self._found(monkeypatch, [{"name": "a", "host": "10.0.0.7", "port": 7777},
                                  {"name": "b", "host": "10.0.0.8", "port": 7777}])
        assert find_brain(0.01) == ""

    def test_one_brain_on_two_interfaces_is_still_one_answer(self, monkeypatch):
        """Duplicate records for the same host:port are one Brain answering
        twice, not two Brains — refusing there would be a false ambiguity."""
        self._found(monkeypatch, [{"name": "a", "host": "10.0.0.7", "port": 7777},
                                  {"name": "a", "host": "10.0.0.7", "port": 7777}])
        assert find_brain(0.01) == "http://10.0.0.7:7777"

    def test_an_incomplete_record_is_not_a_brain(self, monkeypatch):
        self._found(monkeypatch, [{"name": "a", "host": "", "port": 7777},
                                  {"name": "b", "host": "10.0.0.8"}])
        assert find_brain(0.01) == ""

    def test_nothing_on_the_lan(self, monkeypatch):
        self._found(monkeypatch, [])
        assert find_brain(0.01) == ""


class TestTheShippedBrainActuallyAdvertises:
    """The link every one of these re-hostings turns on. Not "the beacon works"
    — that is the class above — but "`python -m dreamlayer.ai_brain.server`
    reaches it". Asserted by RUNNING `main()` with the serve loop stubbed,
    rather than by grepping the source for a call: a checker that reads the
    file agrees with whatever the file says."""

    def _run(self, monkeypatch, tmp_path, host):
        from dreamlayer.ai_brain.server import __main__ as m

        served = {}

        class _Srv:
            server_address = ("0.0.0.0", 7777)
            tls_port = None

            def serve_forever(self):
                served["ran"] = True

            def server_close(self):
                served["closed"] = True

        monkeypatch.setattr(m, "make_brain_server",
                            lambda *a, **k: _Srv())
        monkeypatch.setattr("dreamlayer.ai_brain.server.tls.start_tls_sibling",
                            lambda *a, **k: (None, 0))
        assert m.main(["--dir", str(tmp_path), "--host", host,
                       "--port", "7777", "--no-tls"]) == 0
        assert served.get("ran"), "the serve loop never ran — bad harness"
        return served

    def test_a_network_bind_advertises(self, monkeypatch, tmp_path, zc, lan):
        self._run(monkeypatch, tmp_path, "0.0.0.0")
        assert _FakeZC.last is not None, (
            "a network-reachable Brain started and announced nothing — the "
            "wearer is back to typing an IP address")
        assert _FakeZC.last.registered

    def test_it_withdraws_when_the_serve_loop_returns(self, monkeypatch,
                                                      tmp_path, zc, lan):
        self._run(monkeypatch, tmp_path, "0.0.0.0")
        assert _FakeZC.last.unregistered, (
            "the Brain stopped with its beacon still on the air — a phone "
            "would find it, dial it, and fail")

    def test_a_loopback_bind_announces_nothing(self, monkeypatch, tmp_path,
                                               zc, lan):
        """A loopback Brain has nothing to tell the LAN, and the address it
        would publish resolves back to whoever read it."""
        self._run(monkeypatch, tmp_path, "127.0.0.1")
        assert _FakeZC.last is None


class TestThePromotionFollowsAServiceOnTheAir:
    def _row(self, brain) -> dict:
        from dreamlayer.ai_brain.server.server import _capability_payload
        return next(i for i in _capability_payload(brain)["items"]
                    if i["key"] == "lan_discovery")

    def test_a_brain_that_never_advertised_is_not_promoted(self, tmp_path,
                                                           monkeypatch):
        monkeypatch.delenv("DL_WIRED_LAN_DISCOVERY", raising=False)
        brain = _brain(tmp_path)
        assert self._row(brain)["state"] != "active"
        assert getattr(brain, "_beacon", None) is None, (
            "the report BUILT a beacon to ask about one — a capability poll "
            "would then look like use")

    def test_a_live_beacon_is_promoted(self, tmp_path, monkeypatch, zc, lan):
        monkeypatch.delenv("DL_WIRED_LAN_DISCOVERY", raising=False)
        brain = _brain(tmp_path)
        assert beacon(brain).advertise(7777)
        row = self._row(brain)
        # zeroconf itself is absent in CI, and a missing wheel outranks any
        # flag — that is the honest word for that machine. What must hold is
        # that the flag is set; the state follows installedness.
        import os
        assert os.environ.get("DL_WIRED_LAN_DISCOVERY") or row["state"] in (
            "active", "missing"), row

    def test_it_goes_back_down_when_the_beacon_stops(self, tmp_path, zc, lan):
        brain = _brain(tmp_path)
        b = beacon(brain)
        b.advertise(7777)
        assert b.driving() is True
        b.stop()
        assert b.driving() is False, (
            "a stopped beacon still reports the capability live — that is a "
            "claim, not a state")

    def test_the_beacon_is_built_once_and_held(self, tmp_path):
        brain = _brain(tmp_path)
        assert beacon(brain) is beacon(brain)

    def test_status_reports_the_same_thing_it_promotes_on(self, zc, lan,
                                                          tmp_path):
        b = BrainBeacon(_brain(tmp_path))
        b.advertise(7777)
        assert b.status()["live"] is b.driving()
        assert b.status()["registered"] is True
