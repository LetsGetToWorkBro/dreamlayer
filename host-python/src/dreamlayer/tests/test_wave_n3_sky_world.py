"""Wave N3: open-meteo weather, adsb.lol Skywatch, Skyfield sky lens.

Every network path is behind a fetch seam, so all of this runs offline: query
building (with the ~1 km coordinate rounding — the privacy posture), parsing of
real-shaped payloads, junk tolerance, and the say-lines. The sky lens pins its
local-files-only fallback.
"""
from __future__ import annotations

import json

from dreamlayer.object_lens.sky_lens import SkyLens, default_sky_lens, say_sky
from dreamlayer.plugins import open_meteo as W
from dreamlayer.plugins import skywatch_adsb as A


class TestWeather:
    def test_query_rounds_coordinates_to_a_kilometre(self):
        url = W.build_query(37.774929, -122.419416)
        assert url is not None and url.startswith(W.HOST)
        assert "latitude=37.77" in url and "longitude=-122.42" in url
        assert "37.774" not in url                     # exact position never leaves

    def test_query_rejects_junk(self):
        assert W.build_query("x", 0) is None
        assert W.build_query(91, 0) is None
        assert W.build_query(0, 181) is None

    def test_parse_real_shape(self):
        raw = json.dumps({
            "current": {"temperature_2m": 18.3, "precipitation": 0.0,
                        "weather_code": 2, "wind_speed_10m": 11.2},
            "daily": {"temperature_2m_max": [21.0], "temperature_2m_min": [12.0],
                      "precipitation_probability_max": [55]},
        }).encode()
        w = W.parse_weather(raw)
        assert w["temp_c"] == 18.3 and w["sky"] == "partly cloudy"
        assert w["today"] == {"hi": 21.0, "lo": 12.0, "rain_pct": 55}
        line = W.say_weather(w)
        assert "Partly cloudy" in line and "55% chance of rain" in line

    def test_parse_junk_is_none(self):
        assert W.parse_weather(None) is None
        assert W.parse_weather(b"{not json") is None
        assert W.parse_weather(b"{}") is None

    def test_null_weather_code_keeps_the_temperature(self):
        # a present-but-null code must not sink a valid forecast (refute 2026-07-21)
        raw = json.dumps({"current": {"temperature_2m": 18.3,
                                      "weather_code": None}}).encode()
        w = W.parse_weather(raw)
        assert w is not None and w["temp_c"] == 18.3
        assert w["sky"] == "changing sky"

    def test_current_weather_via_seam(self):
        seen = {}

        def fetch(url):
            seen["url"] = url
            return json.dumps({"current": {"temperature_2m": 9.0,
                                           "weather_code": 61}}).encode()
        w = W.current_weather(51.5074, -0.1278, fetch_fn=fetch)
        assert w["sky"] == "light rain"
        assert seen["url"].startswith(W.HOST)

    def test_default_fetch_pins_host(self):
        assert W._default_fetch("https://evil.example/v1/forecast") is None


class TestSkywatch:
    RAW = json.dumps({"ac": [
        {"flight": "BAW286 ", "lat": 37.9, "lon": -122.5, "alt_baro": 34000,
         "gs": 480.2, "t": "B77W"},
        {"flight": "GROUND1", "lat": 37.7, "lon": -122.4, "alt_baro": "ground"},
        {"flight": "LOW1", "lat": 37.7, "lon": -122.4, "alt_baro": 200},
        {"r": "N123AB", "lat": 37.8, "lon": -122.42, "alt_geom": 4500, "gs": 120},
        {"flight": "NOPOS"},
    ]}).encode()

    def test_parse_filters_and_sorts_nearest_first(self):
        planes = A.parse_planes(self.RAW, 37.7749, -122.4194)
        signs = [p["callsign"] for p in planes]
        assert signs == ["N123AB", "BAW286"]           # ground/low/no-pos dropped
        assert planes[0]["dist_km"] < planes[1]["dist_km"]

    def test_query_rounds_and_bounds(self):
        url = A.build_query(37.774929, -122.419416, radius_nm=9999)
        assert url == f"{A.HOST}/v2/point/37.77/-122.42/250"
        assert A.build_query("x", 0) is None

    def test_overhead_and_say_line(self):
        p = A.overhead(37.7749, -122.4194, fetch_fn=lambda u: self.RAW)
        assert p["callsign"] == "N123AB"
        line = A.say_plane(A.parse_planes(self.RAW, 37.7749, -122.4194)[1])
        assert "BAW286" in line and "34,000 ft" in line and "B77W" in line

    def test_junk_is_empty(self):
        assert A.parse_planes(b"{not json", 0, 0) == []
        assert A.parse_planes(None, 0, 0) == []
        assert A.overhead(0, 0, fetch_fn=lambda u: None) is None

    def test_null_alt_baro_falls_through_to_alt_geom(self):
        # readsb feeds emit alt_baro:null with a valid alt_geom (refute 2026-07-21)
        raw = json.dumps({"ac": [{"flight": "TEST1", "lat": 37.8, "lon": -122.4,
                                  "alt_baro": None, "alt_geom": 34000}]}).encode()
        planes = A.parse_planes(raw, 37.7749, -122.4194)
        assert len(planes) == 1 and planes[0]["alt_ft"] == 34000

    def test_default_fetch_pins_host(self):
        assert A._default_fetch("https://adsbexchange.com/v2/x") is None


class TestSkyLens:
    def test_not_ready_without_wheel_or_files(self, tmp_path):
        lens = SkyLens(str(tmp_path))                  # empty dir → no ephemeris
        assert lens.ready is False
        assert lens.night_sky(37.77, -122.42) == {}
        assert default_sky_lens(str(tmp_path)) is None

    def test_say_sky_lines(self):
        assert say_sky({}) == ""
        line = say_sky({"planets": [("Venus", 20.0, 250.0)], "iss_minutes": 4.0})
        assert "Venus is up" in line and "4 minutes" in line
        quiet = say_sky({"planets": [], "iss_minutes": None})
        assert quiet == ""

    def test_say_sky_keeps_proper_nouns_capitalized(self):
        # str.capitalize() lowercased 'Mars'/'ISS' after char 0 (refute 2026-07-21)
        line = say_sky({"planets": [("Venus", 20.0, 250.0), ("Mars", 30.0, 120.0)],
                        "iss_minutes": 10.0})
        assert "Mars" in line and "ISS" in line and "are up" in line
        iss_only = say_sky({"planets": [], "iss_minutes": 4.0})
        assert iss_only.startswith("The ISS crosses")


def test_sky_capability_registered():
    from dreamlayer import capabilities as C
    cap = {c.key: c for c in C.CAPABILITIES}.get("sky_sense")
    assert cap is not None and cap.extra == "sky" and "skyfield" in cap.modules
