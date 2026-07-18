"""Decode-boundary fuzzing for the figment parser.

`Figment.from_dict` is the hardened boundary for UNTRUSTED figment dicts arriving
over HTTP import (brain_rc.rc_import), BLE transport, and peer CRDT sync
(vault_sync). The existing `test_diff_interpreters` proves the interpreters AGREE
on *valid* figments — but it builds objects with the constructor and filters to
`verify(fig).ok`, so it never drives a *malformed* dict through `from_dict`. That
decode boundary is exactly where an attacker-controlled record lands.

The contract this pins: `from_dict` on ANY input either returns a Figment or
raises a single catchable `FigmentError` (a ValueError subclass) — NEVER a bare
IndexError/AttributeError/RecursionError that would escape a caller's `except`
and crash the surface. (refute 2026-07-18: `duration_range:[5]` / `points:[[1]]`
raised an uncaught IndexError that slipped the CRDT-sync except tuple.)
"""
from __future__ import annotations

import copy

import pytest

from dreamlayer.reality_compiler.v2.figment import Figment, FigmentError

hyp = pytest.importorskip("hypothesis")
from hypothesis import given, settings, HealthCheck   # noqa: E402
from hypothesis import strategies as st               # noqa: E402


# An arbitrary JSON-ish value: the shape an attacker can actually send.
_json = st.recursive(
    st.none() | st.booleans() | st.integers(min_value=-10**6, max_value=10**6)
    | st.floats(allow_nan=True, allow_infinity=True) | st.text(max_size=8),
    lambda children: st.lists(children, max_size=6)
    | st.dictionaries(st.text(max_size=8), children, max_size=6),
    max_leaves=40,
)


@settings(max_examples=400, suppress_health_check=[HealthCheck.too_slow])
@given(_json)
def test_from_dict_only_ever_raises_FigmentError(payload):
    # The whole contract in one line: arbitrary bytes in → a Figment or a
    # FigmentError, never an uncaught crash type.
    try:
        Figment.from_dict(payload)
    except FigmentError:
        pass                                   # the one allowed failure mode


def _valid_figment_dict() -> dict:
    return {
        "name": "f", "initial": "a", "id": "deadbeef0001", "version": 2,
        "scenes": {
            "a": {
                "id": "a", "duration_range": [1.0, 3.0], "tick": "countup",
                "lines": [{"content": "hi", "row": 0}],
                "glyphs": [{"points": [[0.1, 0.2], [0.3, 0.4]], "color": "accent_attention"}],
                "on_timeout": [{"target": "@end"}],
            },
        },
        "counters": {"n": {"name": "n", "start": 0, "lo": 0, "hi": 9}},
    }


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@given(st.randoms(use_true_random=True))
def test_mutating_a_valid_figment_never_crashes_uncaught(rng):
    """Take a valid figment and corrupt one path — truncate a list, retype a
    field, drop a key. This is the mutation class that found the IndexError."""
    d = _valid_figment_dict()
    scene = d["scenes"]["a"]
    mutation = rng.choice([
        lambda: scene.__setitem__("duration_range", [rng.random()]),      # 1-elem range
        lambda: scene.__setitem__("duration_range", "xy"),                # wrong type
        lambda: scene["glyphs"][0].__setitem__("points", [[rng.random()]]),  # 1-elem point
        lambda: scene["glyphs"][0].__setitem__("points", 5),              # not a list
        lambda: scene.__setitem__("lines", [{"row": 0}]),                 # missing content
        lambda: scene.__setitem__("on_timeout", [{"counter_ops": [{}]}]), # missing target
        lambda: d.__setitem__("scenes", [d["scenes"]["a"]]),              # scenes as list
        lambda: d.pop("initial", None),                                   # missing key
        lambda: d.__setitem__("counters", {"n": {"start": "x"}}),         # missing name
    ])
    mutation()
    try:
        Figment.from_dict(copy.deepcopy(d))
    except FigmentError:
        pass


# --- revert-failing anchors: the exact bugs, pinned ---------------------------

def test_one_element_duration_range_is_a_clean_error():
    d = _valid_figment_dict()
    d["scenes"]["a"]["duration_range"] = [5]            # was an uncaught IndexError
    with pytest.raises(FigmentError):
        Figment.from_dict(d)


def test_one_element_glyph_point_is_a_clean_error():
    d = _valid_figment_dict()
    d["scenes"]["a"]["glyphs"][0]["points"] = [[1]]     # was an uncaught IndexError
    with pytest.raises(FigmentError):
        Figment.from_dict(d)


def test_non_dict_payload_is_a_clean_error():
    for bad in ([1, 2, 3], "figment", 42, None):
        with pytest.raises(FigmentError):
            Figment.from_dict(bad)


def test_a_valid_figment_still_decodes_and_round_trips():
    f = Figment.from_dict(_valid_figment_dict())
    assert f.name == "f"
    assert Figment.from_dict(f.to_dict()).to_dict() == f.to_dict()
