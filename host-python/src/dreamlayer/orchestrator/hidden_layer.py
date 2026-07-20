"""orchestrator/hidden_layer.py — the secrets, through the real pipeline.

Two undocumented discoveries, driven by the same temple-tap stream as
everything else (device FSM → BLE → on_button), so the glasses and every
simulator surface share one behavior:

  * seven quick single taps  → Prism, the lost lens. The PrismLens host
    controller emits its real {t="prism"} frame over the bridge and
    halo-lua/display/prism.lua draws the kaleidoscope on-device; twelve
    seconds later the lens folds back in (active=0 → the Lua side's own
    close animation).
  * three quick single taps  → her true colors. A stateless JunoColorsCard
    rides bridge.send_card like any card; eight seconds later ReadyCard is
    re-sent. Skipped in Dream Mode (taps there belong to the tin can).

A burst is evaluated only after the taps go quiet (debounce), so a
seven-tap run never half-fires the three-tap flourish on its way through.
Timers and the clock are injectable; tests run with zero waiting.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from ..dream_mode.prism import PrismLens
from ..hud import cards

TAP_WINDOW_S = 3.5      # a burst lives inside this window
DEBOUNCE_S = 1.3        # quiet time that ends a burst
PRISM_HOLD_S = 12.0     # how long the kaleidoscope plays
COLORS_HOLD_S = 8.0     # how long she keeps her colors


class HiddenLayer:
    """Collects single taps and fires the discovery the burst spells."""

    def __init__(self, bridge, is_dream_fn: Callable[[], bool],
                 prism: Optional[PrismLens] = None,
                 now_fn: Callable[[], float] = time.monotonic,
                 debounce_s: float = DEBOUNCE_S,
                 prism_hold_s: float = PRISM_HOLD_S,
                 colors_hold_s: float = COLORS_HOLD_S,
                 timer_factory=threading.Timer):
        self.bridge = bridge
        self.is_dream = is_dream_fn
        self.prism = prism or PrismLens()
        self._now = now_fn
        self._debounce = debounce_s
        self._prism_hold = prism_hold_s
        self._colors_hold = colors_hold_s
        self._timer_factory = timer_factory
        self._taps: list = []
        self._eval_timer: Optional[threading.Timer] = None
        self._hold_timer: Optional[threading.Timer] = None

    # -- the tap stream -----------------------------------------------------
    def tap(self) -> None:
        ts = self._now()
        self._taps = [t for t in self._taps if ts - t < TAP_WINDOW_S]
        self._taps.append(ts)
        if self._eval_timer is not None:
            self._eval_timer.cancel()
        self._eval_timer = self._timer_factory(self._debounce, self._evaluate)
        self._eval_timer.daemon = True
        self._eval_timer.start()

    # -- burst → discovery --------------------------------------------------
    def _evaluate(self) -> None:
        n, self._taps = len(self._taps), []
        if n >= 7:
            self._enter_prism()
        elif n == 3 and not self.is_dream():
            self._true_colors()

    def _enter_prism(self) -> None:
        try:
            self.bridge.send_raw(self.prism.enter())
        except Exception:
            return                     # no glass in reach — nothing to wake
        self._hold(self._prism_hold, self._exit_prism)

    def _exit_prism(self) -> None:
        try:
            self.bridge.send_raw(self.prism.exit())
        except Exception:
            pass

    def _true_colors(self) -> None:
        try:
            self.bridge.send_card({"type": "JunoColorsCard"}, event="secret")
        except Exception:
            return
        self._hold(self._colors_hold, self._back_to_ready)

    def _back_to_ready(self) -> None:
        try:
            self.bridge.send_card(cards.ready(), event="secret")
        except Exception:
            pass

    def _hold(self, seconds: float, fn) -> None:
        if self._hold_timer is not None:
            self._hold_timer.cancel()
        self._hold_timer = self._timer_factory(seconds, fn)
        self._hold_timer.daemon = True
        self._hold_timer.start()
