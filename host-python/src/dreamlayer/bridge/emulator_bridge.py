from __future__ import annotations
from .base import BridgeBase, PAUSE_ALLOWED_RAW
from .lua_loader import collect_lua

class EmulatorBridge(BridgeBase):
    def __init__(self) -> None:
        super().__init__()
        self._connected = False
        self._bundle: dict[str, str] = {}
        self.state = "boot"
        self.last_card: dict | None = None
        self.raw_frames: list[dict] = []   # dream/raw frames, in send order
        self.dream_active = False
        try:
            import halo_emulator  # type: ignore
            self._emu = halo_emulator
        except Exception:
            self._emu = None

    def connect(self) -> dict:
        self._connected = True
        self.state = "ready"
        return {"device": "halo-emulator", "display": [256, 256], "lua": "5.3", "mock": self._emu is None}

    def disconnect(self) -> None:
        self._connected = False
        self.state = "sleeping"

    def load_lua_app(self, lua_root: str) -> None:
        self._bundle = collect_lua(lua_root)
        self.state = "ready"

    def send_command(self, kind: str, payload: dict | None = None) -> None:
        if kind in ("pause",):               self.state = "paused"
        elif kind in ("resume","show_ready","wake"): self.state = "ready"
        elif kind == "ask":                  self.state = "listening"

    def send_card(self, payload: dict, event: str = "answer_ready") -> None:
        if self.state == "paused" and payload.get("type") != "PrivacyVeilCard":
            return
        self.last_card = payload
        self.state = "paused" if payload.get("type") == "PrivacyVeilCard" else "showing_card"

    def send_raw(self, obj: dict) -> None:
        """Record a raw frame (dream palette/geometry/line_field/sprite).

        Mirrors real_bridge semantics: while privacy-paused, only mode
        control frames (dream_enter/dream_exit) pass — no frame that could
        carry captured signal crosses the pause gate.
        """
        t = obj.get("t")
        if self.state == "paused" and t not in PAUSE_ALLOWED_RAW:
            return
        if t == "dream_enter":
            self.dream_active = True
        elif t == "dream_exit":
            self.dream_active = False
        self.raw_frames.append(obj)

    def inject_event(self, name: str, payload: dict | None = None) -> None:
        if name == "privacy_pause":
            self.state = "paused"
            self.last_card = {"type": "PrivacyVeilCard", "primary": "Privacy Veil",
                              "lines": ["Nothing is being captured"]}
        elif name == "privacy_resume":
            self.state = "ready"
        self._emit_event(name, payload or {})
