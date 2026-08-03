"""test_home_live.py — the glass taps you that the garage is open.

`orchestrator/home_bridge.py` was complete — a LAN-gated reader and a pure
`home_alerts` policy producing the same `Alert` objects the rest of the glasses
use — and nothing constructed it, nothing polled it, and the panel had nowhere
to type the URL. The config fields (`home_assistant_url`, `home_assistant_token`)
existed and were settable through the API with NO reader anywhere in the tree:
the same defect one layer down.

The cooldown is most of what is tested here, because it is most of what makes
this a HUD rather than the reason someone turns notifications off. A garage door
stays open for an hour; polling it every minute and pushing what the policy
returns would put the same card on the glass sixty times.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.home_live import (
    COOLDOWN_S, MAX_PER_POLL, HomeHUD, home)
from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.orchestrator.attention import Alert


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _pushes(brain):
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card, veil_ok)) or 1)
    return seen


class _Bridge:
    def __init__(self, *alerts, boom=False):
        self._alerts = list(alerts)
        self.boom = boom
        self.calls = 0

    def alerts(self):
        self.calls += 1
        if self.boom:
            raise RuntimeError("home assistant unreachable")
        return list(self._alerts)


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


GARAGE = Alert("listen", "The garage is still open", "at home", "garage.door")
SMOKE = Alert("watchout", "Smoke alarm at home", "kitchen", "smoke.kitchen")


class TestTheCooldownIsTheFeature:
    def test_the_same_open_door_is_one_card_not_sixty(self, brain):
        seen = _pushes(brain)
        clock = _Clock()
        h = HomeHUD(brain, bridge=_Bridge(GARAGE), now_fn=clock)
        polls = int(COOLDOWN_S // 60.0) - 1           # stay inside the cooldown
        for _ in range(polls):
            h.poll()
            clock.t += 60.0                          # a minute per poll
        assert len(seen) == 1, f"{len(seen)} cards for one open garage"
        assert h.polls == polls, "the polls themselves should still be counted"

    def test_it_says_so_again_once_the_cooldown_lapses(self, brain):
        seen = _pushes(brain)
        clock = _Clock()
        h = HomeHUD(brain, bridge=_Bridge(GARAGE), now_fn=clock)
        h.poll()
        clock.t += COOLDOWN_S + 1
        h.poll()
        assert len(seen) == 2

    def test_a_different_door_is_its_own_interruption(self, brain):
        """`Alert.key` is what makes the cooldown per-thing rather than global —
        a second door opening must not be silenced by the first."""
        seen = _pushes(brain)
        other = Alert("listen", "The back door is open", "at home", "back.door")
        h = HomeHUD(brain, bridge=_Bridge(GARAGE, other), now_fn=_Clock())
        h.poll()
        assert len(seen) == 2

    def test_an_alert_with_no_key_falls_back_to_its_line(self, brain):
        """Rather than being dropped, and rather than being un-cooled: a policy
        that forgot a key must not become an alert every single poll."""
        seen = _pushes(brain)
        keyless = Alert("listen", "Something at home", "detail", "")
        h = HomeHUD(brain, bridge=_Bridge(keyless), now_fn=_Clock())
        h.poll()
        h.poll()
        assert len(seen) == 1


class TestTheOneThatMattersIsNeverCrowdedOut:
    def test_safety_outranks_the_open_doors(self, brain):
        """A house having a bad minute is exactly when the glass must not become
        a list — and `MAX_PER_POLL` must never be able to drop the smoke alarm
        in favour of four windows."""
        seen = _pushes(brain)
        doors = [Alert("listen", f"Window {i} open", "at home", f"w{i}")
                 for i in range(6)]
        h = HomeHUD(brain, bridge=_Bridge(*doors, SMOKE), now_fn=_Clock())
        h.poll()
        assert len(seen) == MAX_PER_POLL
        assert seen[0][1]["primary"] or seen[0][1]["lines"]
        assert any("Smoke" in str(c) for _k, c, _v in seen), (
            "the smoke alarm was crowded off the glass by open windows")

    def test_a_quiet_house_says_nothing(self, brain):
        seen = _pushes(brain)
        h = HomeHUD(brain, bridge=_Bridge(), now_fn=_Clock())
        assert h.poll() == 0
        assert seen == []


class TestThePosture:
    def test_safety_pierces_the_veil(self, brain):
        """The same rule the ear applies to a smoke alarm it HEARS. The Veil is
        a promise about the record, not a promise to stay silent about a fire —
        and nothing about the alert is stored either way."""
        seen = _pushes(brain)
        HomeHUD(brain, bridge=_Bridge(SMOKE), now_fn=_Clock()).poll()
        assert seen[0][2] is True, "a smoke alarm was suppressed by the shield"

    def test_household_chatter_does_not(self, brain):
        seen = _pushes(brain)
        HomeHUD(brain, bridge=_Bridge(GARAGE), now_fn=_Clock()).poll()
        assert seen[0][2] is False, "an open door was allowed to pierce the veil"

    def test_a_public_url_disables_the_bridge_at_construction(self, brain):
        """`HomeBridge` blanks its own base when the address is not local, so a
        typo cannot egress — asserted here rather than assumed, because this
        module is what supplies the URL."""
        brain.config.home_assistant_url = "https://homeassistant.example.com"
        assert HomeHUD(brain).bridge() is None

    @pytest.mark.parametrize("url", ["http://127.0.0.1:8123",
                                     "http://192.168.1.10:8123",
                                     "http://10.0.0.5:8123"])
    def test_a_lan_url_is_accepted(self, brain, url):
        brain.config.home_assistant_url = url
        assert HomeHUD(brain).bridge() is not None

    def test_the_token_never_reaches_a_card(self, brain):
        # A recognisable marker, NOT a realistic-looking Home Assistant token.
        # The first version of this used a real JWT header (`eyJhbGciOi…`) for
        # verisimilitude and gitleaks flagged the file — correctly: a scanner
        # cannot tell a fixture from a leak, and a repo that trains its
        # contributors to wave that finding through is worse off than one with
        # a slightly less realistic test.
        brain.config.home_assistant_token = "ha-token-MUST-NOT-APPEAR"
        seen = _pushes(brain)
        HomeHUD(brain, bridge=_Bridge(SMOKE), now_fn=_Clock()).poll()
        assert seen, "nothing was pushed, so this asserts nothing"
        assert "MUST-NOT-APPEAR" not in str(seen)


class TestItNeverBreaksTheBrain:
    def test_an_unreachable_house_is_not_a_crash(self, brain):
        h = HomeHUD(brain, bridge=_Bridge(boom=True), now_fn=_Clock())
        assert h.poll() == 0
        assert h.polls == 0                          # it did not answer

    def test_nothing_configured_polls_nothing(self, brain):
        h = HomeHUD(brain)
        assert h.configured() is False
        assert h.poll() == 0

    def test_no_thread_is_started_for_a_brain_with_no_house(self, brain):
        """Which is almost all of them — a daemon waking every minute to
        rediscover there is still no URL is a cost with no possible payoff."""
        assert HomeHUD(brain).start() is False

    def test_a_configured_brain_starts_one_and_stops_it(self, brain):
        brain.config.home_assistant_url = "http://127.0.0.1:8123"
        h = HomeHUD(brain)
        assert h.start(interval=3600.0) is True
        assert h.start(interval=3600.0) is True      # idempotent
        h.stop()

    def test_a_push_that_raises_is_absorbed(self, brain):
        def _boom(kind, card=None, veil_ok=False):
            raise RuntimeError("bridge closed")
        brain.push_event = _boom
        h = HomeHUD(brain, bridge=_Bridge(SMOKE), now_fn=_Clock())
        assert h.poll() == 0
        assert h.driving() is False


class TestSavingTheUrlInThePanelActuallyDoesSomething:
    """`start_home_hud` starts nothing for a Brain with no URL — which is the
    state every Brain boots in — and `HomeHUD` caches the bridge it built from
    that config. Without a rebuild, a wearer would save a setting that did
    nothing until the next restart, with the panel reading it back perfectly."""

    def test_a_config_post_rebuilds_and_restarts_the_poller(self, brain):
        assert brain.start_home_hud() is False
        assert home(brain).bridge() is None          # cached as "no house"
        brain.apply_config({"home_assistant_url": "http://127.0.0.1:8123"})
        assert home(brain).configured() is True
        assert home(brain).bridge() is not None, (
            "the saved URL did nothing until the next restart")
        brain.stop_home_hud()

    def test_the_panel_has_somewhere_to_type_it(self):
        """The config fields existed and were settable through the API with no
        input anywhere in the panel — a setting nobody could reach."""
        import pathlib

        from dreamlayer.ai_brain.server import panel
        src = pathlib.Path(panel.__file__).read_text(encoding="utf-8")
        assert 'id="haUrl"' in src and 'id="haKey"' in src
        assert 'home_assistant_url:$("haUrl").value.trim()' in src
        assert 'body.home_assistant_token=hk' in src

    def test_the_saved_token_is_never_echoed_back(self):
        src_ok = 'c.config.home_assistant_token==="set"'
        import pathlib

        from dreamlayer.ai_brain.server import panel
        src = pathlib.Path(panel.__file__).read_text(encoding="utf-8")
        assert src_ok in src, "the panel would render the raw token into a field"


class TestItReportsItselfHonestly:
    """`home_hud` is `kind="service"`, so the capability meter can only ever
    say "external" about it — there is no dormant/active axis for a
    `DL_WIRED_` flag to move, and inventing one would be a claim in a place
    designed not to carry claims."""

    def test_no_dl_wired_flag_is_invented_for_a_service(self):
        import pathlib

        import dreamlayer.capabilities as cap
        from dreamlayer.ai_brain.server import server as srv
        assert "home_hud" not in cap._PROMOTED_AT_RUNTIME
        assert "home_hud" not in cap._NOT_WIRED
        src = pathlib.Path(srv.__file__).read_text(encoding="utf-8")
        assert 'env["DL_WIRED_HOME_HUD"]' not in src

    def test_the_state_stays_external(self):
        import dreamlayer.capabilities as cap
        assert cap.state(cap._BY_KEY["home_hud"]) == "external"

    def test_the_status_endpoint_carries_the_real_state(self, brain):
        from dreamlayer.ai_brain.server.server import _home_status
        assert _home_status(brain) == {"configured": False, "polls": 0,
                                       "pushed": 0, "live": False}
        h = home(brain)
        h._bridge, h._built = _Bridge(SMOKE), True
        h._now = _Clock()
        _pushes(brain)
        h.poll()
        got = _home_status(brain)
        assert got["pushed"] == 1 and got["live"] is True

    def test_asking_does_not_build_one(self, brain):
        from dreamlayer.ai_brain.server.server import _home_status
        _home_status(brain)
        assert getattr(brain, "_home_hud", None) is None, (
            "a status poll constructed the thing it was reporting on")

    def test_a_configured_house_with_nothing_wrong_is_not_live(self, brain):
        """The distinction the counter exists for. Polling successfully proves
        the transport; a house with nothing wrong is the normal and desirable
        state, and reporting that as a live capability would be describing the
        wiring rather than the feature."""
        h = HomeHUD(brain, bridge=_Bridge(), now_fn=_Clock())
        h.poll()
        assert h.polls == 1
        assert h.driving() is False

    def test_it_is_built_once_and_held(self, brain):
        assert home(brain) is home(brain)
