#!/usr/bin/env python3
"""scripts/run_demo_confluence.py — dinner for two, one entangled sky.

Two simulated wearers, A and M, across a table. The full arc:

  1. the bond: propose → speak the code → accept → confirm
  2. convergence: their inner weathers settle together — the shared sky
     merges into one coherent front
  3. drift: M's weather storms away — the sky splits, a seam stands
     between them and widens
  4. a TinCan ping: A taps single-double — light pulses on M's rim
  5. a Weather Gift: A sends this morning's kitchen light — M's sky
     plays it for thirty seconds
  6. a Crossing: both rhythms already meet at the café on Tuesdays —
     a shared future ghost shimmers on both horizons
  7. M's veil goes up mid-dinner: A's sky fades to solo — privacy wins
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "host-python" / "src"))

from dreamlayer.confluence import (                       # noqa: E402
    BondManager, EntangledSky, TinCan, SharedRhythms,
    export_claims, wrap_gift, unwrap_gift,
)
from dreamlayer.dream_mode.premonition import RecurrenceModel  # noqa: E402
from dreamlayer.dream_mode.weather_ledger import WeatherSnapshot  # noqa: E402

NOW = 1_700_000_000.0
assert time.gmtime(NOW).tm_wday == 1


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


class Veil:
    def __init__(self):
        self.allow = True

    def allow_capture(self):
        return self.allow


def colors(y, cb, cr):
    return [{"idx": i, "y": y, "cb": cb, "cr": cr} for i in range(1, 5)]


def show(who, frames):
    for f in frames:
        if f["t"] == "confluence":
            if f["mode"] == "merged":
                print(f"  [{who}] sky MERGED — one front "
                      f"(togetherness {f['tg']}%)")
            elif f["mode"] == "split":
                print(f"  [{who}] sky SPLIT — seam at "
                      f"{f['seam_dd'] / 10:.0f}°, gap {f['gap_deg']}°, "
                      f"peer half rgb{tuple(f['peer_rgb'])} "
                      f"(togetherness {f['tg']}%)")
            else:
                print(f"  [{who}] sky SOLO — the partner faded")


def main() -> None:
    clock = Clock()
    veil_m = Veil()

    print("=" * 64)
    print("1. THE BOND — explicit, mutual, revocable")
    a = BondManager(now_fn=clock)
    m = BondManager(privacy=veil_m, now_fn=clock)
    offer = a.propose("dinner")
    print(f'   A proposes; the code between them: "{offer.code}"')
    m.accept(offer.bond_id, offer.code)
    a.confirm(offer.bond_id)
    print("   both sides live:", a.live_bond() is not None
          and m.live_bond() is not None)

    sky_a = EntangledSky(a, now_fn=clock)   # what A's display shows
    sky_m = EntangledSky(m, now_fn=clock)

    print("\n2. CONVERGENCE — dinner settles, two nervous systems align")
    for _ in range(25):
        clock.t += 0.5
        sky_a.receive(m.send_weather(0.28, colors(500, 380, 420)).to_wire())
        sky_m.receive(a.send_weather(0.30, colors(520, 400, 400)).to_wire())
        show("A", sky_a.tick(0.30, colors(520, 400, 400)))
        show("M", sky_m.tick(0.28, colors(500, 380, 420)))

    print("\n3. DRIFT — M's storm builds; the sky splits on both faces")
    for step in range(25):
        clock.t += 0.5
        m_state = min(0.95, 0.28 + step * 0.05)
        sky_a.receive(m.send_weather(m_state,
                                     colors(300, 200, 700)).to_wire())
        sky_m.receive(a.send_weather(0.25,
                                     colors(520, 400, 400)).to_wire())
        show("A", sky_a.tick(0.25, colors(520, 400, 400)))
        show("M", sky_m.tick(m_state, colors(300, 200, 700)))

    print("\n4. TINCAN — A taps single-double: light on M's rim")
    can = TinCan(a, now_fn=clock)
    wire = can.compose(["single", "double"])
    frame = TinCan.render_frame(wire, side_deg=90.0)
    print(f"   M's rim pulses: {frame['pulses']} ms at "
          f"{frame['side_dd'] / 10:.0f}° — not a word said")

    print("\n5. WEATHER GIFT — this is what my morning felt like")
    snap = WeatherSnapshot(ts=NOW - 6 * 3600, place="kitchen",
                           colors=colors(700, 460, 380), amplitude=0.2)
    gift = wrap_gift(a, snap)
    frames = unwrap_gift(m, gift)
    print(f"   M's sky plays A's {gift['gift']['hour']:02d}:00 kitchen "
          f"light: {len(frames)} palette frames over 30s")

    print("\n6. CROSSING — where their rhythms already meet")
    ra, rm = RecurrenceModel(), RecurrenceModel()
    for weeks in (1, 2):
        ts = NOW - weeks * 7 * 86400
        day = ts - (time.gmtime(ts).tm_hour * 3600
                    + time.gmtime(ts).tm_min * 60 + time.gmtime(ts).tm_sec)
        ra.observe("memory", "coffee together", day + 15 * 3600, place="cafe")
        rm.observe("memory", "afternoon reading", day + 15 * 3600,
                   place="cafe")
    key = a.bond(offer.bond_id).key
    shared = SharedRhythms(ra, key)
    found = shared.update(export_claims(rm, key))
    print(f"   crossings found: {len(found)} — Tuesday "
          f"{found[0].hour:02d}:00, place never exchanged "
          f"(salted hash {found[0].place_hash[:8]}…)")

    print("\n7. THE VEIL — M pauses; privacy beats togetherness")
    veil_m.allow = False
    assert m.send_weather(0.5, colors(500, 400, 400)) is None
    clock.t += 13                                # A's sky notices the quiet
    show("A", sky_a.tick(0.25, colors(520, 400, 400)))
    print("   nothing of M crosses the bond while the veil is up")

    print("=" * 64)
    print("dinner over. dissolve is one tap away, and the bond expires "
          "on its own by morning.")


if __name__ == "__main__":
    main()
