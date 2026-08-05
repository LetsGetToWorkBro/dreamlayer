"""Every device Lua file compiles, under the same interpreter the glasses run.

`.github/workflows/lua.yml` runs luacheck, which is the real gate for undefined
globals and shadowing. Two gaps sit outside it and this closes both:

* **`display/cinema_v2_prototypes/` is excluded from luacheck entirely**
  (`.luacheckrc: exclude_files`). That is 720 lines with no gate of any kind.
  Nothing outside the directory requires them today — the only `require` of a
  `proto_*` module comes from a sibling prototype — so the exclusion is
  correct and this is not a reachability complaint. But unchecked code that
  compiles today stays compiling only by luck, and the day somebody wires one
  up they are wiring code nothing ever parsed.

* **the luacheck job is path-filtered** to `halo-lua/**`. A change made
  anywhere else cannot run it. This runs in the ordinary suite.

`lupa.lua53` is the same interpreter the raster harness drives the renderer
with, so "compiles" here means the device's Lua 5.3, not a lookalike parser.
This is deliberately only a COMPILE check — luacheck still owns undefined
globals and shadowing, and duplicating that here would be a second, worse
copy of a gate that already works.
"""
from __future__ import annotations

import pathlib

import pytest

try:
    from lupa import lua53
    LUPA = True
except ImportError:                                  # pragma: no cover
    LUPA = False

LUA_ROOT = pathlib.Path(__file__).resolve().parents[4] / "halo-lua"


def _lua_files() -> list[pathlib.Path]:
    return sorted(LUA_ROOT.rglob("*.lua"))


def test_the_scan_actually_finds_the_device_lua():
    """Without this the compile test below passes by finding nothing.

    `rglob` on a missing directory yields an empty list, every assertion in
    the loop is skipped, and a green run means the tree was never read — the
    failure this repo keeps meeting (CLAUDE.md #1). The floor is a non-vacuity
    guard, not a size policy.
    """
    assert LUA_ROOT.is_dir(), f"the device Lua tree is not at {LUA_ROOT}"
    files = _lua_files()
    assert len(files) >= 50, (
        f"only {len(files)} .lua files found — the scan has probably stopped "
        f"reaching the tree rather than 50 modules having been deleted")
    names = {p.name for p in files}
    assert "renderer.lua" in names, "the renderer is outside the scan"
    assert any("proto_" in n for n in names), (
        "the luacheck-excluded prototypes are outside the scan — they are the "
        "main reason this test exists")


@pytest.mark.skipif(not LUPA, reason="lupa not installed")
def test_every_device_lua_file_compiles():
    rt = lua53.LuaRuntime()
    broken = []
    for path in _lua_files():
        try:
            rt.compile(path.read_text(encoding="utf-8"))
        except Exception as exc:                     # noqa: BLE001
            broken.append(f"{path.relative_to(LUA_ROOT)}: "
                          f"{str(exc).splitlines()[0][:120]}")
    assert not broken, (
        "device Lua that does not compile — the glasses would fail to load "
        "these:\n  " + "\n  ".join(broken))
