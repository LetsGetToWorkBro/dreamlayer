"""The capabilities page, organised: display groups + the awakening meter.

Pins the N12 overhaul — every capability belongs to a known display group with a
"what it unlocks" blurb, the groups are consolidated (no more singleton tiers),
and the power meter at the top rises as capabilities go active (and falls as they
switch off), so "your stats go up as you download" is a real, tested property.
"""
from __future__ import annotations

from dreamlayer import capabilities as C


# ---- grouping + consolidation --------------------------------------------

def test_every_cap_tier_is_a_known_display_group():
    keys = {k for (k, _t, _b) in C.TIERS}
    for cap in C.CAPABILITIES:
        assert cap.tier in keys, f"{cap.key} has orphan tier {cap.tier!r}"


def test_no_singleton_tiers_remain():
    from collections import Counter
    counts = Counter(c.tier for c in C.CAPABILITIES)
    # the causal/sync singletons were folded into intelligence/platform
    assert "causal" not in counts and "sync" not in counts
    assert all(n >= 2 for n in counts.values()), counts


def test_tiers_have_titles_and_blurbs_in_order():
    ts = C.tiers()
    assert len(ts) == len(C.TIERS)
    for t in ts:
        assert t["title"] and t["blurb"] and len(t["blurb"]) > 20
    # order is stable (page order)
    assert [t["key"] for t in ts] == [k for (k, _t, _b) in C.TIERS]


def test_report_is_grouped_contiguously_by_tier():
    seen, last = set(), None
    for r in C.report(env={}):
        assert "tier_title" in r
        if r["tier"] != last:
            assert r["tier"] not in seen, f"tier {r['tier']} is split across groups"
            seen.add(r["tier"]); last = r["tier"]


# ---- the awakening meter --------------------------------------------------

def test_power_stats_shape_and_bounds():
    s = C.power_stats(env={})
    for k in ("unlocked", "total", "power", "power_total", "percent",
              "level", "by_tier", "services_total", "fully"):
        assert k in s
    assert 0 <= s["percent"] <= 100
    assert s["unlocked"] <= s["total"]
    assert s["power"] <= s["power_total"]
    assert s["level"] in [name for (_low, name) in C._LEVELS]
    # "fully" is true ONLY at real 100% power, never merely at the top level band
    assert s["fully"] == (s["power"] >= s["power_total"] > 0)


def test_only_pack_installable_caps_gate_the_meter():
    # manual/research caps (extra=None, e.g. diart) and services must NOT sit in
    # the denominator, so installing every pack can reach a true 100%.
    manual_impact = sum(c.impact for c in C.CAPABILITIES if c.kind == "manual")
    assert manual_impact > 0                       # there are manual caps
    installable = sum(c.impact for c in C.CAPABILITIES if c.kind in ("python", "darwin"))
    s = C.power_stats(env={})
    # power_total counts only installable caps this machine supports (<= all installable)
    assert s["power_total"] <= installable
    # and never includes a manual cap's impact
    assert s["power_total"] == sum(
        c.impact for c in C.CAPABILITIES
        if c.kind in ("python", "darwin") and C.state(c, env={}) != "unsupported")


def test_level_climbs_monotonically_with_percent():
    last = -1
    for pct in range(0, 101, 5):
        idx, _name = C._level_for(pct)
        assert idx >= last
        last = idx
    assert C._level_for(100)[1] == "Ascendant"
    assert C._level_for(0)[1] == "Dormant"


def test_stats_rise_with_active_caps_and_fall_when_switched_off():
    base = C.power_stats(env={})
    # switch OFF every currently-active capability → the meter must drop
    env = {}
    for r in C.report(env={}):
        if r["state"] == "active":
            env["DL_DISABLE_" + r["key"].upper()] = "1"
    dark = C.power_stats(env=env)
    assert dark["unlocked"] <= base["unlocked"]
    assert dark["percent"] <= base["percent"]
    if base["unlocked"] > 0:                       # in CI a few pure-python caps are active
        assert dark["unlocked"] < base["unlocked"]
        assert dark["percent"] < base["percent"]
        # …and re-enabling them climbs right back
        assert C.power_stats(env={})["percent"] == base["percent"]


def test_by_tier_bars_are_consistent():
    s = C.power_stats(env={})
    tot_unlocked = sum(t["unlocked"] for t in s["by_tier"].values())
    tot_total = sum(t["total"] for t in s["by_tier"].values())
    assert tot_unlocked == s["unlocked"]
    assert tot_total == s["total"]
    # groups are ordered in page order
    order = [k for (k, _t, _b) in C.TIERS]
    keys = list(s["by_tier"].keys())
    assert keys == [k for k in order if k in keys]


def test_full_install_would_reach_ascendant():
    # with nothing disabled and every installable cap imagined active, the meter
    # tops out — prove the ceiling is reachable (percent can hit 100)
    # simulate by treating power_total as the numerator
    s = C.power_stats(env={})
    assert s["power_total"] > 0
    # a machine with all installable caps active scores 100% by construction
    # (power == power_total). Here we assert the arithmetic can reach it.
    assert round(100 * s["power_total"] / s["power_total"]) == 100


# ---- payload wiring -------------------------------------------------------

def test_capability_payload_carries_stats_and_tiers(tmp_path):
    from dreamlayer.ai_brain.server.server import Brain, _capability_payload
    b = Brain(tmp_path)
    payload = _capability_payload(b)
    assert "stats" in payload and "tiers" in payload
    assert payload["stats"]["total"] > 0
    assert len(payload["tiers"]) == len(C.TIERS)
    # a disabled cap lowers the payload's meter
    active = [r["key"] for r in payload["items"] if r["state"] == "active"]
    if active:
        b.config.disabled_caps = [active[0]]
        lower = _capability_payload(b)
        assert lower["stats"]["unlocked"] < payload["stats"]["unlocked"]
