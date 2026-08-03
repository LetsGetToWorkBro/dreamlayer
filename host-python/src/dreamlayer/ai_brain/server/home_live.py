"""The glass taps you that the garage is open — `home_hud`, Brain-side.

WHAT WAS MISSING
----------------
`orchestrator/home_bridge.py` is complete: a LAN-gated Home Assistant reader
(`HomeBridge.states`) and a pure policy (`home_alerts`) that turns household
facts into the same `Alert` objects the rest of the glasses use. Nothing
constructed it, there was nowhere to put the URL, and nothing polled it. Its
only intended consumer was the `Orchestrator` the shipped Brain never builds
(`decisions/0001`).

So the capability's promise — *"leave home blind; with Home Assistant the glass
taps you that the garage is still open, or that the smoke alarm is going"* — had
no path from a running Brain to a single card.

THE COOLDOWN IS THE FEATURE
---------------------------
A doorbell entity stays `on` for a while. A garage door stays open for an hour.
Polling every 60 s and pushing what `home_alerts` returns would put the same
card on the glass sixty times, which is not a HUD — it is the reason people
switch notifications off. `AttentionPolicy` already owns per-key cooldowns for
exactly this and is the right primitive, so this holds one and consults it
rather than inventing a second rule.

`Alert.key` is what makes that work: `home_alerts` sets one per real thing, so
"garage still open" is one interruption per cooldown however many polls see it,
and a DIFFERENT door opening is its own.

PRIVACY AND POSTURE
-------------------
  * LAN-only, structurally. `HomeBridge` blanks its own base URL when the
    address is not local (`is_local_endpoint`), so a public URL disables the
    bridge at construction rather than being refused per request. Nothing here
    can re-enable it.
  * The token rides an `Authorization` header to the wearer's own house. It is
    stored in the Brain's config beside the other service credentials and never
    logged, never pushed, never put in a card.
  * SAFETY PIERCES THE VEIL, household chatter does not. A `watchout` (smoke,
    CO, gas, water) is the one class of thing the glasses are allowed to
    interrupt an incognito stretch for — the same rule `note_acoustic_context`
    already applies to a smoke alarm it HEARS. A `listen` (a door left open)
    stays quiet under the shield.

    That asymmetry is deliberate and worth being able to defend: the Veil is a
    promise about the RECORD, not a promise to let the wearer's house burn down
    silently. Nothing about the alert is stored either way.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("dreamlayer.home_live")

#: How often the house is asked. Home Assistant is on the LAN and `/api/states`
#: is one small request, so this is cheap — but it is also not a real-time
#: channel (that would be the websocket API), and a minute is the honest
#: granularity for "you left and the garage is open" rather than for a doorbell.
POLL_S = 60.0

#: One interruption per real thing per half hour. `AttentionPolicy`'s own
#: default, used rather than re-picked: a garage door stays open for an hour and
#: a doorbell entity stays `on` for minutes, so without this the same card lands
#: on the glass every poll.
COOLDOWN_S = 1800.0

#: Alerts pushed from one poll, most important first. A house having a bad
#: minute is exactly when the glass must not become a list — three cards is
#: already more than anyone reads while walking out of a door.
MAX_PER_POLL = 3


class HomeHUD:
    """The house, on the glass. Built once and held for the session."""

    def __init__(self, brain, bridge=None, now_fn=time.time):
        self.brain = brain
        self._bridge = bridge
        self._built = bridge is not None
        self._now = now_fn
        self._stop: threading.Event | None = None
        self._raised: dict = {}
        #: Cards genuinely pushed. The promotion proof — a configured URL is not
        #: a reachable house, and a reachable house with nothing wrong has
        #: nothing to say, which is the correct outcome and not a live
        #: capability.
        self.pushed = 0
        self.polls = 0

    # ---------------------------------------------------------------- bridge

    def bridge(self):
        if not self._built:
            self._built = True
            url = (getattr(self.brain.config, "home_assistant_url", "") or "").strip()
            token = (getattr(self.brain.config, "home_assistant_token", "") or "").strip()
            if not url:
                return None
            try:
                from ...orchestrator.home_bridge import default_home_bridge
                self._bridge = default_home_bridge(url, token)
                if self._bridge is None:
                    # `HomeBridge` blanks a non-local base URL at construction,
                    # so this is the wearer having typed a public address. Say
                    # so — silently doing nothing looks identical to a house
                    # with nothing wrong.
                    log.warning("[home] the Home Assistant URL is not on this "
                                "LAN — the bridge is local-only by design")
            except Exception as exc:                 # noqa: BLE001
                log.info("[home] bridge unavailable: %s", type(exc).__name__)
                self._bridge = None
        return self._bridge

    def configured(self) -> bool:
        return bool((getattr(self.brain.config, "home_assistant_url", "") or "").strip())

    # ------------------------------------------------------------------ poll

    def poll(self) -> int:
        """Ask the house once. Returns how many cards reached the glass."""
        b = self.bridge()
        if b is None:
            return 0
        try:
            alerts = b.alerts()
        except Exception as exc:                     # noqa: BLE001
            log.info("[home] states unavailable: %s", type(exc).__name__)
            return 0
        self.polls += 1
        sent = 0
        for alert in self._fresh(alerts)[:MAX_PER_POLL]:
            if self._push(alert):
                sent += 1
        return sent

    def _fresh(self, alerts) -> list:
        """Alerts not raised within the cooldown, most urgent first.

        Sorted before slicing, so a house with a smoke alarm AND four open
        windows shows the smoke alarm — `MAX_PER_POLL` must never be able to
        drop the one that matters in favour of the ones that do not.
        """
        now = float(self._now())
        out = []
        for a in (alerts or []):
            key = str(getattr(a, "key", "") or getattr(a, "clue", ""))
            if not key:
                continue
            # `.get(key)` and an explicit None, NOT a 0.0 default. With a
            # default of zero, "never raised" becomes "raised at the epoch",
            # and `now - 0 < COOLDOWN_S` suppresses the FIRST sighting of
            # everything whenever `now` is smaller than the cooldown. Real
            # wall-clock never is, so this would have been invisible in
            # production and wrong on any machine with a bad clock — and it
            # made the first test written against it silently pass zero cards.
            last = self._raised.get(key)
            if last is not None and now - float(last) < COOLDOWN_S:
                continue
            self._raised[key] = now
            out.append(a)
        out.sort(key=lambda a: 0 if getattr(a, "level", "") == "watchout" else 1)
        return out

    def _push(self, alert) -> bool:
        try:
            from ...hud import cards
            urgent = getattr(alert, "level", "") == "watchout"
            card = cards.hark(
                clue=getattr(alert, "clue", "") or "Something at home.",
                detail=getattr(alert, "detail", "") or "at home",
                importance="urgent" if urgent else "normal")
            # Safety pierces the Veil; household chatter does not. The same rule
            # the ear applies to a smoke alarm it HEARS — the Veil is a promise
            # about the record, not a promise to stay silent about a fire.
            got = self.brain.push_event("home", card, veil_ok=urgent)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[home] push failed: %s", type(exc).__name__)
            return False
        if got:
            self.pushed += 1
        return bool(got)

    # ------------------------------------------------------------- scheduler

    def start(self, interval: float = POLL_S) -> bool:
        """Ask the house on a cadence. False when nothing is configured.

        Idempotent, and it does NOT start a thread for a Brain with no Home
        Assistant — which is almost all of them. A daemon thread waking every
        minute to discover there is still no URL is a cost with no possible
        payoff.
        """
        if self._stop is not None:
            return True
        if not self.configured():
            return False
        stop = threading.Event()
        self._stop = stop

        def loop():
            first = True
            while not stop.wait(3.0 if first else interval):
                first = False
                try:
                    self.poll()
                except Exception:                    # noqa: BLE001
                    log.warning("[home] poll tick failed", exc_info=True)
        threading.Thread(target=loop, daemon=True,
                         name="dreamlayer-home").start()
        return True

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
            self._stop = None

    # ---------------------------------------------------------------- report

    def driving(self) -> bool:
        """A card genuinely on the glass.

        Not "a URL is configured" and not "the house answered": a house with
        nothing wrong is the normal, desirable state and produces no alerts, so
        polling successfully proves the transport and not the capability.
        """
        return self.pushed > 0

    def status(self) -> dict:
        return {"configured": self.configured(), "polls": self.polls,
                "pushed": self.pushed, "live": self.driving()}


def home(brain) -> HomeHUD:
    got = getattr(brain, "_home_hud", None)
    if got is None:
        got = HomeHUD(brain)
        brain._home_hud = got
    return got
