"""plugins/open_meteo.py — real weather with honest egress (open-meteo.com).

InnerWeather and the WeatherLedger paint from ambient signals; this grounds them
in the actual sky. Open-Meteo is open-source, keyless, and self-hostable — so
the egress caption stays one honest line: coordinates out (rounded to ~1 km),
forecast back. Point `HOST` at your own instance and even that line disappears.

Connector discipline (openfoodfacts/currency): a pinned host, the hardened
egress primitives (`read_capped`, `no_redirect_opener`), a `fetch_fn` seam so
every test runs offline, and None-never-raise on any failure.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Callable, Optional

from ._egress import no_redirect_opener, read_capped

HOST = "https://api.open-meteo.com"

# WMO weather codes → a line a person (or Juno) can say. Subset that covers the
# codes open-meteo actually emits; unknown codes read as "changing sky".
_WMO = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "rain showers", 81: "heavy showers", 82: "violent showers",
    85: "snow showers", 86: "heavy snow showers", 95: "a thunderstorm",
    96: "a thunderstorm with hail", 99: "a severe thunderstorm",
}


def build_query(lat: float, lon: float) -> Optional[str]:
    """The forecast URL. Coordinates are validated and ROUNDED to 2 decimals
    (~1 km) — the sky is the same across a kilometre, so the exact position
    never leaves the device."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    q = urllib.parse.urlencode({
        "latitude": round(lat, 2), "longitude": round(lon, 2),
        "current": "temperature_2m,precipitation,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto", "forecast_days": 1,
    })
    return f"{HOST}/v1/forecast?{q}"


def parse_weather(raw: Optional[bytes]) -> Optional[dict]:
    """{temp_c, wind_kmh, precip_mm, sky, today:{hi, lo, rain_pct}} or None."""
    if not raw:
        return None
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
        cur = data.get("current") or {}
        daily = data.get("daily") or {}
        code = int(cur.get("weather_code", -1))
        out = {
            "temp_c": round(float(cur["temperature_2m"]), 1),
            "wind_kmh": round(float(cur.get("wind_speed_10m", 0) or 0), 1),
            "precip_mm": round(float(cur.get("precipitation", 0) or 0), 2),
            "sky": _WMO.get(code, "changing sky"),
        }
        try:
            out["today"] = {
                "hi": round(float(daily["temperature_2m_max"][0]), 1),
                "lo": round(float(daily["temperature_2m_min"][0]), 1),
                "rain_pct": int(daily["precipitation_probability_max"][0] or 0),
            }
        except (KeyError, IndexError, TypeError, ValueError):
            pass                                   # current conditions still stand
        return out
    except (ValueError, KeyError, TypeError):
        return None


def _default_fetch(url: str, timeout: float = 6.0) -> Optional[bytes]:
    if not url.startswith(HOST + "/"):
        return None                                # host pin is structural
    try:
        with no_redirect_opener().open(url, timeout=timeout) as r:
            return read_capped(r, 256 * 1024)
    except Exception:                              # noqa: BLE001
        return None


def current_weather(lat: float, lon: float,
                    fetch_fn: Optional[Callable[[str], Optional[bytes]]] = None
                    ) -> Optional[dict]:
    """The one call: rounded coordinates out, a parsed forecast back, or None."""
    url = build_query(lat, lon)
    if url is None:
        return None
    return parse_weather((fetch_fn or _default_fetch)(url))


def say_weather(w: Optional[dict]) -> str:
    """A line Juno can speak, or ''."""
    if not w:
        return ""
    line = f"{w['sky'].capitalize()}, {w['temp_c']:g} degrees"
    today = w.get("today")
    if today:
        line += f" — up to {today['hi']:g} today"
        if today.get("rain_pct", 0) >= 40:
            line += f", {today['rain_pct']}% chance of rain"
    return line + "."
