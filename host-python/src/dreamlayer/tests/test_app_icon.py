"""test_app_icon.py — the shipped app icon is full-bleed, not a bordered box.

The screenshots showed the Dock/Finder icon as a small mark inside a grey bevel
ring with transparent rounded corners that flash black on a dark menu bar. The
fix (packaging/make_fullbleed_icon.py) repaints the ground edge-to-edge and lets
macOS apply its own squircle. These guard the two invariants that keep it that
way: no transparent pixels anywhere (no "black box"), and the web/native copy
stays byte-identical to the packaged source.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL.Image")

_PKG = Path(__file__).resolve().parents[3] / "packaging"
_APP_ICON = (Path(__file__).resolve().parents[1]
             / "ai_brain" / "server" / "assets" / "app_icon.png")


@pytest.mark.parametrize("name", ["icon.png", "icon_small.png"])
def test_icon_is_square_and_fully_opaque(name):
    im = PIL.open(_PKG / name).convert("RGBA")
    w, h = im.size
    assert w == h, f"{name} is not square ({w}x{h})"
    lo, _hi = im.split()[3].getextrema()
    assert lo == 255, (
        f"{name} has transparent pixels — macOS masks its own squircle, so any "
        "transparency here reads as the black-box / bordered look we removed")
    # the four corners specifically must be opaque (the transparent rounded
    # corners were the 'black box' on a dark background)
    for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        assert im.getpixel((x, y))[3] == 255, f"{name} corner {(x, y)} is transparent"


def test_web_and_native_copy_is_in_sync():
    # server/assets/app_icon.png is a byte copy of the packaged icon; if someone
    # regenerates one without the other the panel + window icon drift out of date
    assert _APP_ICON.exists(), "app_icon.png missing"
    assert _APP_ICON.read_bytes() == (_PKG / "icon.png").read_bytes(), (
        "app_icon.png is out of sync with packaging/icon.png — "
        "run packaging/make_fullbleed_icon.py")


_DOCK_ICON = _APP_ICON.parent / "app_icon_dock.png"


def test_dock_icon_is_pre_shaped_squircle():
    # The window-open Dock tile is stamped via NSApp.setApplicationIconImage_,
    # which shows the bitmap AS IS — macOS does NOT apply its squircle/safe-area
    # there. So this variant must be PRE-SHAPED: transparent corners (a squircle,
    # not a hard edge-to-edge square that renders oversized next to neighbours)
    # and an inset body (a safe-area margin). This is the exact inverse of the
    # full-bleed invariant above, and the two must not be confused.
    assert _DOCK_ICON.exists(), (
        "app_icon_dock.png missing — run packaging/make_dock_icon.py")
    im = PIL.open(_DOCK_ICON).convert("RGBA")
    w, h = im.size
    assert w == h == 1024, f"dock icon is {w}x{h}, expected 1024x1024"
    # the four corners are transparent (the baked squircle)
    for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        assert im.getpixel((x, y))[3] == 0, (
            f"dock corner {(x, y)} is opaque — the squircle mask didn't apply, "
            "so the Dock tile would render as a hard square (the 'goes big' bug)")
    # the body is opaque at centre and inset from the edges (a safe-area margin,
    # so the tile is sized like a real app icon rather than edge-to-edge)
    assert im.getpixel((w // 2, h // 2))[3] == 255, "dock icon has no solid body"
    bbox = im.getbbox()
    assert bbox is not None and bbox[0] >= 40 and bbox[1] >= 40 and \
        bbox[2] <= w - 40 and bbox[3] <= h - 40, (
        f"dock art bbox {bbox} reaches the edge — it must be inset (safe area)")
