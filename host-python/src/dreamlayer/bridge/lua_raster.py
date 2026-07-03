"""bridge/lua_raster.py

Pixel raster harness for the device Lua display code.

Boots a lupa Lua runtime with ``package.path`` pointed at ``halo-lua/``
and installs a real Lua table ``frame`` (so the device code's
``type(_G.frame) == "table"`` guards pass) whose ``display`` functions
are backed by a Pillow rasterizer. Every ``frame.display.show()``
snapshots the canvas, so animated signatures can be exported as PNG
sequences.

Why this exists (Cinema v2): the v1 golden pipeline rendered cards from
a *parallel Python renderer* whose dispatch gaps shipped committed black
goldens while the device Lua drew fine (see docs/CINEMA_V1_JUDGMENT.md,
Wrong #1). This harness rasterizes the device code itself — the Lua that
ships is the Lua that gets reviewed.

Fidelity model
--------------
- Primitives: ``clear/show/text/line/rect/circle/set_pixel/bitmap`` plus
  ``assign_color_ycbcr``. Geometry is pixel-accurate; text uses a PIL
  font at a fixed device-ish size, center-anchored (the codebase's draw
  convention).
- Dynamic palette slots: ``assign_color_ycbcr(slot, y, cb, cr)`` updates
  a 16-entry palette model (BT.601 full-range inverse, 0-1023 scale).
  After the Lua side reserves its dynamic slots, call
  :meth:`LuaRasterHarness.sync_dynamic_slots` — any subsequent draw call
  whose color equals a reserved base hex renders with the slot's *live*
  color, exactly as the indexed-color hardware would.
- No alpha anywhere. If it can't be done with palette slots on 4bpp,
  it can't be done here either.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

SIZE = 256
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
_FONT_PX = 13


def _load_font(px: int = _FONT_PX):
    for cand in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(cand, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _hex_to_rgb(color: int) -> tuple[int, int, int]:
    color = int(color) & 0xFFFFFF
    return (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF


def _ycbcr_to_rgb(y: float, cb: float, cr: float) -> tuple[int, int, int]:
    """Inverse of palette.lua hex_to_ycbcr (BT.601 full range, 0-1023)."""
    y, cb, cr = y / 4.0, cb / 4.0, cr / 4.0
    r = y + 1.402 * (cr - 128.0)
    g = y - 0.344136 * (cb - 128.0) - 0.714136 * (cr - 128.0)
    b = y + 1.772 * (cb - 128.0)
    clamp = lambda v: max(0, min(255, int(v + 0.5)))
    return clamp(r), clamp(g), clamp(b)


class RasterDisplay:
    """Python back-end for the injected ``frame.display`` Lua table."""

    def __init__(self) -> None:
        self.canvas = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
        self._draw = ImageDraw.Draw(self.canvas)
        self._font = _load_font()
        self._fonts: dict[int, object] = {_FONT_PX: self._font}
        self.frames: list[Image.Image] = []
        # slot -> live RGB; base hex -> slot (learned via sync)
        self._slot_rgb: dict[int, tuple[int, int, int]] = {}
        self._slot_by_hex: dict[int, int] = {}
        self.draw_calls = 0
        self.font_calls = 0

    def set_font(self, fid, sz, sc) -> None:
        """Model of frame.display.set_font (Meridian Solid).

        Maps sz*sc to a PIL face of the same pixel size — goldens carry
        the hierarchy the panel will. A state write like
        assign_color_ycbcr: counted in font_calls, not draw_calls.
        """
        del fid  # single reference face; fid is a device-side concern
        px = max(6, int(round(float(sz) * float(sc))))
        font = self._fonts.get(px)
        if font is None:
            font = _load_font(px)
            self._fonts[px] = font
        self._font = font
        self.font_calls += 1

    # -- palette model ------------------------------------------------
    def bind_slot(self, base_hex: int, slot: int) -> None:
        self._slot_by_hex[int(base_hex)] = int(slot)
        self._slot_rgb.setdefault(int(slot), _hex_to_rgb(base_hex))

    def assign_color_ycbcr(self, slot, y, cb, cr) -> None:
        self._slot_rgb[int(slot)] = _ycbcr_to_rgb(float(y), float(cb), float(cr))

    def _resolve(self, color) -> tuple[int, int, int]:
        color = int(color)
        slot = self._slot_by_hex.get(color)
        if slot is not None and slot in self._slot_rgb:
            return self._slot_rgb[slot]
        return _hex_to_rgb(color)

    # -- primitives (frame.display.*) ----------------------------------
    def clear(self, color=0x000000) -> None:
        self._draw.rectangle([0, 0, SIZE - 1, SIZE - 1], fill=self._resolve(color))

    def show(self) -> None:
        self.frames.append(self.canvas.copy())

    def text(self, s, x, y, color=0xFFFFFF) -> None:
        self.draw_calls += 1
        self._draw.text((float(x), float(y)), str(s), font=self._font,
                        fill=self._resolve(color), anchor="mm")

    def line(self, x0, y0, x1, y1, color) -> None:
        self.draw_calls += 1
        self._draw.line([(float(x0), float(y0)), (float(x1), float(y1))],
                        fill=self._resolve(color), width=1)

    def rect(self, x, y, w, h, color, filled=False) -> None:
        self.draw_calls += 1
        box = [float(x), float(y), float(x) + float(w) - 1, float(y) + float(h) - 1]
        if filled:
            self._draw.rectangle(box, fill=self._resolve(color))
        else:
            self._draw.rectangle(box, outline=self._resolve(color), width=1)

    def circle(self, cx, cy, r, color, filled=False) -> None:
        self.draw_calls += 1
        box = [float(cx) - float(r), float(cy) - float(r),
               float(cx) + float(r), float(cy) + float(r)]
        if filled:
            self._draw.ellipse(box, fill=self._resolve(color))
        else:
            self._draw.ellipse(box, outline=self._resolve(color), width=1)

    def set_pixel(self, x, y, color) -> None:
        self.draw_calls += 1
        self._draw.point((float(x), float(y)), fill=self._resolve(color))

    def bitmap(self, *_args) -> None:  # sprites: out of raster scope
        self.draw_calls += 1

    # -- export ---------------------------------------------------------
    @staticmethod
    def _circular(img: Image.Image) -> Image.Image:
        mask = Image.new("L", (SIZE, SIZE), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, SIZE - 1, SIZE - 1], fill=255)
        out = img.convert("RGBA")
        out.putalpha(mask)
        return out

    def save_frame(self, path: Path, index: int = -1) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = self.frames[index] if self.frames else self.canvas
        self._circular(frame).save(path)
        return path

    def last_frame(self) -> Image.Image:
        return self.frames[-1] if self.frames else self.canvas.copy()

    def bright_pixel_count(self, threshold: int = 12) -> int:
        """Lit pixels in the last shown frame — the anti-black-golden assert."""
        gray = self.last_frame().convert("L")
        hist = gray.histogram()
        return sum(hist[threshold:])


_FRAME_TABLE_LUA = """
__imu = nil
frame = {
  imu_data = function() return __imu end,
  display = {
    clear   = function(c)            __raster.clear(c or 0x000000) end,
    show    = function()             __raster.show() end,
    text    = function(s, x, y, c)   __raster.text(s, x, y, c or 0xFFFFFF) end,
    line    = function(a, b, c, d, col)      __raster.line(a, b, c, d, col) end,
    rect    = function(x, y, w, h, col, f)   __raster.rect(x, y, w, h, col, f or false) end,
    circle  = function(x, y, r, col, f)      __raster.circle(x, y, r, col, f or false) end,
    set_pixel = function(x, y, col)          __raster.set_pixel(x, y, col) end,
    bitmap  = function(...)          __raster.bitmap(...) end,
    set_font = function(fid, sz, sc) __raster.set_font(fid, sz, sc or 1.0) end,
    assign_color_ycbcr = function(i, y, cb, cr) __raster.assign_color_ycbcr(i, y, cb, cr) end,
  },
}
"""


class LuaRasterHarness:
    """Lua runtime + raster display, package.path aimed at halo-lua/."""

    def __init__(self, lua_root: Optional[Path] = None) -> None:
        import lupa

        self.lua_root = Path(lua_root) if lua_root else self._default_root()
        self.display = RasterDisplay()
        self.rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        root = str(self.lua_root).replace("\\", "/")
        self.rt.execute(
            f'package.path = "{root}/?.lua;{root}/?/init.lua;" .. package.path'
        )
        self.rt.globals()["__raster"] = self.display
        self.rt.execute(_FRAME_TABLE_LUA)

    @staticmethod
    def _default_root() -> Path:
        here = Path(__file__).resolve()
        for parent in here.parents:
            cand = parent / "halo-lua"
            if (cand / "main.lua").exists():
                return cand
        raise FileNotFoundError("halo-lua/ not found above " + str(here))

    def require(self, module: str):
        result = self.rt.eval(f'require("{module}")')
        # Lua 5.4+ require returns (module, loaderdata); unwrap the module
        if isinstance(result, tuple):
            return result[0]
        return result

    def execute(self, lua_src: str):
        return self.rt.execute(lua_src)

    def eval(self, lua_expr: str):
        return self.rt.eval(lua_expr)

    def set_imu(self, pitch: Optional[float], roll: float = 0.0) -> None:
        """Script the ``frame.imu_data()`` stub (None = sensor absent).

        Parallax and any IMU-reactive display code become testable and
        goldenable headless: set a pose per tick, the Lua reads it as
        the device would.
        """
        if pitch is None:
            self.rt.execute("__imu = nil")
        else:
            self.rt.execute(
                f"__imu = {{ pitch = {float(pitch)}, roll = {float(roll)} }}"
            )

    def sync_dynamic_slots(self) -> None:
        """Mirror palette.lua's reserved dynamic bank into the raster model.

        Call after the Lua side has reserved its slots (e.g. after
        requiring display modules) so draws in a base color follow the
        slot's live YCbCr, as they would on the indexed hardware.

        Both module instances are synced: Lua keys package.loaded by the
        literal require string, so ``display.palette`` (renderer/focus/
        horizon side) and ``display/palette`` (dream/prism side) hold
        separate reservation registries over the same hardware slots
        (see palette_cycle.lua's header). Dream weather and the Prism
        kaleidoscope reserve the sky bank on the slash instance — without
        it their palette-cycled color never shows in the raster.
        """
        for module in ("display.palette", "display/palette"):
            try:
                pal = self.require(module)
            except Exception:
                continue
            for name in pal.reserved_names().values():
                slot = pal.dynamic_slot(name)
                base = pal.dynamic_color(name)
                if slot is not None and base is not None:
                    self.display.bind_slot(int(base), int(slot))
