"""reality_compiler/emulator.py — Pure-Python Halo display emulator.

No C extension required. Simulates:
  - 640×400 display (Halo color microOLED spec)
  - frame.display.text() / clear() / show()
  - frame.button.single_click / double_click / long_press callbacks
  - frame.bluetooth.receive_callback()
  - frame.sleep() (time-compressed: sleeps 1ms per simulated second)
  - frame.battery_level() → configurable mock value
  - Framebuffer pixel brightness inspection

Usage
-----
    from dreamlayer.reality_compiler.emulator import HaloEmulator

    emu = HaloEmulator()
    emu.load_lua(lua_code_string)
    emu.start()
    emu.inject_double_click()
    emu.wait(timeout=1.0)
    img = emu.get_framebuffer()   # PIL Image or None
    bright = emu.bright_pixel_count()
    emu.stop()

Note: Full Lua execution requires the `lupa` package (pip install lupa).
Without lupa the emulator runs in stub mode: events are recorded but Lua
is not executed.  Stub mode is sufficient for structural codegen tests.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

try:
    import lupa  # type: ignore
    _LUPA_AVAILABLE = True
except ImportError:
    _LUPA_AVAILABLE = False

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

DISPLAY_W = 640
DISPLAY_H = 400
_SLEEP_RATIO = 0.001  # 1 ms per simulated second (100× compression)


class _DisplayState:
    """Mutable display model written to by Lua frame.display.* calls."""

    def __init__(self) -> None:
        self.texts: list[tuple[str, int, int]] = []  # (text, x, y)
        self.dirty = False
        self.shown_texts: list[tuple[str, int, int]] = []

    def text(self, msg: str, x: int, y: int) -> None:
        self.texts.append((str(msg), int(x), int(y)))
        self.dirty = True

    def clear(self) -> None:
        self.texts.clear()
        self.dirty = True

    def show(self) -> None:
        self.shown_texts = list(self.texts)
        self.dirty = False

    def bright_pixel_count(self) -> int:
        """Estimate visible pixels from shown texts (no Pillow needed)."""
        return sum(len(t) * 8 for t, _, _ in self.shown_texts)

    def to_image(self) -> Optional["Image.Image"]:
        if not _PIL_AVAILABLE:
            return None
        img = Image.new("RGB", (DISPLAY_W, DISPLAY_H), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        for text, x, y in self.shown_texts:
            draw.text((x, y), text, fill=(255, 255, 255))
        return img


class HaloEmulator:
    """Halo display emulator — pure Python, no hardware required."""

    def __init__(self, battery_level: int = 75) -> None:
        self._battery_level = battery_level
        self._display = _DisplayState()
        self._events: list[str] = []
        self._bt_callback: Optional[Callable] = None
        self._button_callbacks: dict[str, Optional[Callable]] = {
            "single_click": None,
            "double_click": None,
            "long_press": None,
        }
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lua_code: Optional[str] = None
        self._lua_runtime = None

    # ------------------------------------------------------------------
    # Lua loading
    # ------------------------------------------------------------------

    def load_lua(self, code: str) -> None:
        self._lua_code = code

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the emulator (non-blocking)."""
        self._running = True
        if _LUPA_AVAILABLE and self._lua_code:
            self._thread = threading.Thread(
                target=self._run_lua, daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def wait(self, timeout: float = 1.0) -> None:
        """Sleep for *timeout* real seconds (emulator runs concurrently)."""
        time.sleep(timeout)

    # ------------------------------------------------------------------
    # Event injection (callable from test code)
    # ------------------------------------------------------------------

    def inject_single_click(self) -> None:
        self._events.append("single_click")
        cb = self._button_callbacks.get("single_click")
        if cb:
            try:
                cb()
            except Exception:
                pass

    def inject_double_click(self) -> None:
        self._events.append("double_click")
        cb = self._button_callbacks.get("double_click")
        if cb:
            try:
                cb()
            except Exception:
                pass

    def inject_long_press(self) -> None:
        self._events.append("long_press")
        cb = self._button_callbacks.get("long_press")
        if cb:
            try:
                cb()
            except Exception:
                pass

    def inject_bluetooth(self, data: bytes) -> None:
        self._events.append("bluetooth")
        if self._bt_callback:
            try:
                self._bt_callback(data)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Framebuffer inspection
    # ------------------------------------------------------------------

    def get_framebuffer(self) -> Optional["Image.Image"]:
        return self._display.to_image()

    def bright_pixel_count(self) -> int:
        """Estimate visible content without Pillow."""
        return self._display.bright_pixel_count()

    def shown_texts(self) -> list[tuple[str, int, int]]:
        return list(self._display.shown_texts)

    def events_log(self) -> list[str]:
        return list(self._events)

    # ------------------------------------------------------------------
    # Lua execution (lupa backend)
    # ------------------------------------------------------------------

    def _run_lua(self) -> None:
        if not _LUPA_AVAILABLE:
            return
        try:
            rt = lupa.LuaRuntime(unpack_returned_tuples=True)
            self._lua_runtime = rt
            self._inject_frame_api(rt)
            rt.execute(self._lua_code)
        except Exception:
            pass  # Lua errors are non-fatal in emulator context

    def _inject_frame_api(self, rt) -> None:
        """Inject the frame.* API into a lupa LuaRuntime."""
        display = self._display
        button_callbacks = self._button_callbacks
        battery = self._battery_level
        sleep_ratio = _SLEEP_RATIO
        bt_store = {"cb": None}

        # frame.display
        rt.execute("frame = {}")
        rt.execute("frame.display = {}")
        rt.execute("frame.button = {}")
        rt.execute("frame.bluetooth = {}")

        g = rt.globals()

        class _Display:
            def text(self, msg, x, y):
                display.text(msg, x, y)
            def clear(self):
                display.clear()
            def show(self):
                display.show()

        class _Button:
            def single_click(self, fn):
                button_callbacks["single_click"] = fn
            def double_click(self, fn):
                button_callbacks["double_click"] = fn
            def long_press(self, fn):
                button_callbacks["long_press"] = fn

        class _Bluetooth:
            def receive_callback(self, fn):
                bt_store["cb"] = fn
            def send(self, data):
                pass  # host would receive this

        g.frame = type("frame", (), {
            "display": _Display(),
            "button": _Button(),
            "bluetooth": _Bluetooth(),
            "sleep": lambda s: time.sleep(s * sleep_ratio),
            "battery_level": lambda: battery,
            "imu_data": lambda: None,
        })()

        self._bt_callback = lambda d: bt_store["cb"](d) if bt_store["cb"] else None
