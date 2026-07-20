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

Concurrency: taps arrive on the BLE loop thread; the debounce/hold timers fire
on their own threading.Timer threads. A single lock guards the tap list and the
timer slots so the two never race; the bridge I/O itself runs OUTSIDE the lock
(a blocking send must never stall an incoming tap).
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from ..dream_mode.prism import PrismLens
from ..hud import cards

DEBOUNCE_S = 1.3        # quiet time that ends a burst (also the max gap WITHIN one)
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
        self._lock = threading.RLock()
        self._taps: list = []
        self._eval_timer: Optional[threading.Timer] = None
        self._hold_timer: Optional[threading.Timer] = None
        self._pending_exit: Optional[Callable[[], None]] = None

    # -- the tap stream -----------------------------------------------------
    def tap(self) -> None:
        with self._lock:
            ts = self._now()
            # A gap longer than the debounce means the previous burst already
            # ended (its _evaluate has run, or is about to) — so start fresh.
            # Counting every tap of the CURRENT burst (not an absolute time
            # window) means a steadily-paced seven-tap run stays seven and wakes
            # the lens, instead of being pruned down to three and misfiring the
            # colours flourish (refute 2026-07-20).
            if self._taps and ts - self._taps[-1] >= self._debounce:
                self._taps = []
            self._taps.append(ts)
            if self._eval_timer is not None:
                self._eval_timer.cancel()
            self._eval_timer = self._timer_factory(self._debounce, self._evaluate)
            self._eval_timer.daemon = True
            self._eval_timer.start()

    # -- burst → discovery --------------------------------------------------
    def _evaluate(self) -> None:
        with self._lock:                      # atomic read+reset vs a racing tap()
            n, self._taps = len(self._taps), []
        # Dream Mode taps belong to the tin can — NEITHER egg fires there (the
        # prism branch was previously ungated, so seven taps in a bond-less Dream
        # session woke the lens; refute 2026-07-20). Decisions + bridge I/O run
        # OUTSIDE the lock so a blocking send can't stall an incoming tap.
        if self.is_dream():
            return
        if n >= 7:
            self._enter_prism()
        elif n == 3:
            self._true_colors()

    def _enter_prism(self) -> None:
        self._fold_current()           # fold back any egg already up first
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
        self._fold_current()
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

    def _hold(self, seconds: float, fn: Callable[[], None]) -> None:
        with self._lock:
            if self._hold_timer is not None:
                self._hold_timer.cancel()
            self._pending_exit = fn
            self._hold_timer = self._timer_factory(seconds, self._fire_hold)
            self._hold_timer.daemon = True
            self._hold_timer.start()

    def _fire_hold(self) -> None:
        with self._lock:
            fn, self._pending_exit = self._pending_exit, None
            self._hold_timer = None
        if fn:
            fn()                       # run the fold-back OUTSIDE the lock

    def _fold_current(self) -> None:
        """Run the fold-back owed for whatever egg is currently up, so starting a
        second egg never strands the first. Without this, opening her colours
        while the prism was holding cancelled the prism's own active=0 frame —
        and since the on-glass lens has no auto-close, it stuck forever (refute
        2026-07-20). No-op when nothing is up."""
        with self._lock:
            if self._hold_timer is not None:
                self._hold_timer.cancel()
                self._hold_timer = None
            fn, self._pending_exit = self._pending_exit, None
        if fn:
            fn()

    def stop(self) -> None:
        """Cancel pending timers (orchestrator teardown / bridge swap) so no
        stale prism or colours frame fires into a later session."""
        with self._lock:
            for t in (self._eval_timer, self._hold_timer):
                if t is not None:
                    t.cancel()
            self._eval_timer = self._hold_timer = None
            self._pending_exit = None
