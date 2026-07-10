"""test_provenance_glyph.py — the on-device provenance shield (INNOVATION 5.4b).

The host discloses that a shared figment's voice is third-party (impersonation.py
/ the safety card); this is the on-glass counterpart — a shared figment
(meta.origin=="shared") wears a small shield at the top of the ring, drawn by
figment_stage.lua, so third-party content can never pass as the system's own.
"""
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

HALO_LUA = Path(__file__).resolve().parents[4] / "halo-lua"

HARNESS = '''
local stage = require("app.figment_stage")
local drawn, handlers = {}, {}
stage.bind({
  display = {
    text  = function(s, x, y, opts) drawn[#drawn+1] = {text=s, x=x, y=y} end,
    clear = function() drawn = {} end,
    show  = function() _G.__shown = drawn end,
  },
  send    = function() end,
  battery = function() return 100 end,
  random  = function() return 0.5 end,
})
stage.register({ register = function(t, fn) handlers[t] = fn end })
return {
  stage    = stage,
  glyph    = stage.PROVENANCE_GLYPH,
  handlers = handlers,
  shown    = function() return _G.__shown or {} end,
}
'''


def _lua(rt, obj):
    if isinstance(obj, dict):
        t = rt.table()
        for k, v in obj.items():
            t[k] = _lua(rt, v)
        return t
    if isinstance(obj, list):
        t = rt.table()
        for i, v in enumerate(obj, 1):
            t[i] = _lua(rt, v)
        return t
    return obj


def _fig(origin=None):
    fig = {
        "id": "f1", "initial": "a", "version": 2,
        "scenes": {"a": {"id": "a", "duration_sec": 100.0,
                         "lines": [{"content": "HELLO", "row": 0, "size": "md",
                                    "color": "text_primary"}]}},
    }
    if origin is not None:
        fig["meta"] = {"origin": origin}
    return fig


@pytest.fixture
def rig():
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{HALO_LUA}/?.lua;" .. package.path')
    return rt, rt.execute(HARNESS)


def _drive(rt, h, fig):
    """put + swap + one render tick through the stage's own handlers."""
    put = _lua(rt, {"t": "figment_put", "id": fig["id"], "figment": fig})
    swap = _lua(rt, {"t": "figment_swap", "id": fig["id"]})
    h["handlers"]["figment_put"](put)
    h["handlers"]["figment_swap"](swap)
    h["stage"].tick(0.05)
    shown = h["shown"]()
    return [row["text"] for row in shown.values()]


def test_shared_figment_draws_the_shield(rig):
    rt, h = rig
    texts = _drive(rt, h, _fig(origin="shared"))
    assert h["glyph"] in texts and "HELLO" in texts


def test_first_party_figment_has_no_shield(rig):
    rt, h = rig
    texts = _drive(rt, h, _fig(origin=None))
    assert h["glyph"] not in texts and "HELLO" in texts


def test_is_shared_predicate(rig):
    rt, h = rig
    _drive(rt, h, _fig(origin="shared"))
    assert h["stage"].is_shared() is True
