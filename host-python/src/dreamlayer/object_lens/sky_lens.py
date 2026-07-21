"""object_lens/sky_lens.py — the "look up" lens (Skyfield): the night sky, named.

Point your face up: which bright planets are above the horizon, and when the ISS
next crosses. Skyfield is research-grade astronomy in pure Python — and this
lens is deliberately OFFLINE: it computes only from local data files you (or a
pack) place in a directory, never downloading:

    de421.bsp      — the JPL planetary ephemeris (planets + moon)
    stations.tle   — a TLE set containing the ISS (for pass prediction)

Absent the wheel (extras group `sky`) or the files, `ready` is False and
night_sky() returns {} — the glasses simply don't have this sense yet. The
timescale uses Skyfield's builtin data (`builtin=True`), so nothing here ever
reaches the network.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("dreamlayer.sky_lens")

# the bright, namable things worth a whisper (ephemeris keys → spoken names)
_PLANETS = (("moon", "the Moon"), ("venus", "Venus"), ("mars", "Mars"),
            ("jupiter barycenter", "Jupiter"), ("saturn barycenter", "Saturn"))


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


class SkyLens:
    """Local-file astronomy. `available` is the wheel; `ready` once the
    ephemeris actually loaded from `data_dir` ($DL_SKY_DIR)."""

    dep = "skyfield"
    available = _has("skyfield")

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = Path(data_dir or os.environ.get("DL_SKY_DIR") or "")
        self._eph: Any = None
        self._ts: Any = None
        self._iss: Any = None
        self._loaded = False

    def _load(self) -> bool:
        if self._loaded:
            return self._eph is not None
        self._loaded = True
        if not self.available or not self.data_dir.is_dir():
            return False
        bsp = self.data_dir / "de421.bsp"
        if not bsp.is_file():
            return False
        try:
            from skyfield.api import load, load_file  # type: ignore
            self._ts = load.timescale(builtin=True)   # no deltat download
            self._eph = load_file(str(bsp))
            self._load_iss()
        except Exception as exc:                   # noqa: BLE001
            log.info("[sky] ephemeris load failed: %s", exc)
            self._eph = None
        return self._eph is not None

    def _load_iss(self) -> None:
        """Parse the ISS out of a local TLE file ourselves — no loader, no
        network. Missing file or no ISS line → passes just aren't predicted."""
        tle = self.data_dir / "stations.tle"
        if not tle.is_file():
            return
        try:
            from skyfield.api import EarthSatellite  # type: ignore
            lines = tle.read_text(errors="replace").splitlines()
            for i, line in enumerate(lines):
                # name must START with ISS — 'SWISSCUBE' contains it (refute note)
                if line.strip().upper().startswith("ISS") and i + 2 < len(lines):
                    self._iss = EarthSatellite(lines[i + 1], lines[i + 2],
                                               line.strip(), self._ts)
                    return
        except Exception as exc:                   # noqa: BLE001
            log.info("[sky] TLE parse failed: %s", exc)
            self._iss = None

    @property
    def ready(self) -> bool:
        return self._load()

    def night_sky(self, lat: float, lon: float,
                  when_ts: Optional[float] = None) -> dict:
        """{planets: [(name, alt_deg, az_deg)…], iss_minutes: float|None} for
        an observer at lat/lon — {} when the lens isn't ready. Planets below
        5° altitude are omitted (you can't see them anyway)."""
        if not self._load():
            return {}
        try:
            import datetime as _dt

            from skyfield.api import wgs84  # type: ignore
            t = self._ts.from_datetime(
                _dt.datetime.fromtimestamp(float(when_ts), tz=_dt.timezone.utc)
            ) if when_ts else self._ts.now()
            here = wgs84.latlon(float(lat), float(lon))
            observer = self._eph["earth"] + here
            planets = []
            for key, name in _PLANETS:
                try:
                    alt, az, _ = observer.at(t).observe(
                        self._eph[key]).apparent().altaz()
                    if alt.degrees > 5.0:
                        planets.append((name, round(alt.degrees, 1),
                                        round(az.degrees, 1)))
                except (KeyError, ValueError):
                    continue
            return {"planets": planets,
                    "iss_minutes": self._next_iss_minutes(here, t)}
        except Exception as exc:                   # noqa: BLE001
            log.error("[sky] night_sky failed: %s", exc)
            return {}

    def _next_iss_minutes(self, here, t) -> Optional[float]:
        if self._iss is None:
            return None
        try:
            t1 = self._ts.tt_jd(t.tt + 0.5)        # look 12 hours ahead
            times, events = self._iss.find_events(here, t, t1,
                                                  altitude_degrees=10.0)
            for ti, ev in zip(times, events):
                if ev == 0:                        # rise above 10°
                    return round((ti.tt - t.tt) * 24 * 60, 1)
            return None
        except Exception as exc:                   # noqa: BLE001
            log.debug("[sky] ISS pass predict failed: %s", exc)
            return None


def say_sky(sky: dict) -> str:
    """The whisper for a look up, or ''."""
    if not sky:
        return ""
    bits = []
    planets = sky.get("planets") or []
    if planets:
        bits.append(", ".join(p[0] for p in planets[:3]) +
                    (" is up" if len(planets) == 1 else " are up"))
    iss = sky.get("iss_minutes")
    if iss is not None and iss <= 30:
        bits.append(f"the ISS crosses in {iss:g} minutes")
    if not bits:
        return ""
    s = " — ".join(bits) + "."
    # str.capitalize() would lowercase 'Mars'/'ISS' after char 0 (refute
    # 2026-07-21) — uppercase only the first character
    return s[:1].upper() + s[1:]


def default_sky_lens(data_dir: Optional[str] = None) -> Optional[SkyLens]:
    lens = SkyLens(data_dir)
    return lens if lens.ready else None
