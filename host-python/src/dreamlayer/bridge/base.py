from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable

# Raw frame types (msg["t"]) crossing the BLE boundary. Mirrors
# halo-lua/ble/message_types.lua — update both in lockstep.
RAW_FRAME_TYPES = frozenset({
    "palette",        # palette weather: {colors: [{idx,y,cb,cr}], duration_ms}
    "geometry",       # legacy particle/line distortion
    "line_field",     # Line Field 2.0: {v: [48 ints]} — one MTU frame
    "sprite",         # TxSprite bitmap: {data, x?, y?}
    "sprite_avatar",  # 32x32 contact avatar sprite (contacts ONLY)
    "dream_enter",
    "dream_exit",
    "horizon",        # Meridian day-ring: {seq, paused, v: [dd,code,…]}
    # Reality Compiler figments (host → app/figment_stage.lua) — the hub
    # deploys native timers/behaviors straight to the glasses, no Brain needed.
    "figment_put", "figment_swap", "figment_revoke", "figment_text",
})

# Raw frames still allowed while privacy-paused (mode control only; no
# frame that could carry captured signal passes the pause gate).
PAUSE_ALLOWED_RAW = frozenset({"dream_enter", "dream_exit"})


def pause_allows_raw(obj: dict) -> bool:
    """Gate for raw frames while privacy-paused. Mode control passes;
    the EMPTY horizon pause frame passes too — the absence of marks must
    be deliverable or the rim keeps showing pre-pause state
    (docs/cinema_v2/horizon_frame.md). A horizon frame carrying marks is
    captured signal and never passes."""
    t = obj.get("t")
    if t in PAUSE_ALLOWED_RAW:
        return True
    if t == "horizon" and not obj.get("v"):
        return True
    return False


class BridgeBase(ABC):
    def __init__(self) -> None:
        self._event_cb: Callable[[str, dict], None] | None = None
    def on_event(self, cb: Callable[[str, dict], None]) -> None:
        self._event_cb = cb
    def _emit_event(self, name: str, payload: dict | None = None) -> None:
        if self._event_cb:
            self._event_cb(name, payload or {})
    @abstractmethod
    def connect(self) -> dict: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @abstractmethod
    def load_lua_app(self, lua_root: str) -> None: ...
    @abstractmethod
    def send_command(self, kind: str, payload: dict | None = None) -> None: ...
    @abstractmethod
    def send_card(self, payload: dict, event: str = "answer_ready") -> None: ...
    @abstractmethod
    def send_raw(self, obj: dict) -> None:
        """Send a raw (non-card) frame — dream palette/geometry/line_field/
        sprite/dream_enter/dream_exit. See RAW_FRAME_TYPES."""
        ...
    @abstractmethod
    def inject_event(self, name: str, payload: dict | None = None) -> None: ...
