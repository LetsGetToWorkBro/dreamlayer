"""bridge/frame_sdk.py — an optional adapter for Brilliant Labs **Frame** glasses.

DreamLayer targets Halo; Frame is Brilliant's earlier device with a Python SDK
(frame-sdk / frame-msg). This adapter lets the same card/answer payloads light up
a Frame for prototyping, without touching the Halo bridge.

ADD-alongside: `bridge/base.py`, `bridge/real_bridge.py`, `bridge/emulator_bridge.py`
are untouched. This is a thin, separate display surface — `connect / show_text /
show_card / clear` — not a BridgeBase subclass, so it imposes nothing on the host.

frame-sdk is optional (extras group `platform`). When absent, the adapter records
what it *would* have shown into `sent` (useful for tests/demos) and reports
`available = False`; nothing here can break the Halo path.
"""
from __future__ import annotations

import logging
from typing import List, Optional

log = logging.getLogger("dreamlayer.frame_sdk")

try:
    import frame_sdk  # type: ignore  # noqa: F401
    _HAS_FRAME = True
except ImportError:
    _HAS_FRAME = False


class FrameDisplay:
    available = _HAS_FRAME

    def __init__(self):
        self._frame = None
        self.sent: List[dict] = []          # record of shown payloads (fallback + real)
        self.connected = False

    def connect(self) -> dict:
        if not _HAS_FRAME:
            self.connected = False
            return {"ok": False, "reason": "frame-sdk not installed"}
        try:
            from frame_sdk import Frame  # type: ignore
            self._frame = Frame()
            self.connected = True
            return {"ok": True}
        except Exception as exc:
            log.warning("[frame_sdk] connect failed: %s", exc)
            self.connected = False
            return {"ok": False, "reason": str(exc)}

    def show_text(self, text: str, x: int = 1, y: int = 1) -> None:
        self.sent.append({"kind": "text", "text": text, "x": x, "y": y})
        if self._frame is not None:
            try:
                self._frame.display.show_text(text, x, y)  # type: ignore[attr-defined]
            except Exception as exc:
                log.warning("[frame_sdk] show_text failed: %s", exc)

    def show_card(self, card: dict) -> None:
        """Flatten a DreamLayer card to Frame's text display via noa-style
        patterns (title + first line)."""
        from .noa_patterns import card_to_frame_lines
        lines = card_to_frame_lines(card)
        self.sent.append({"kind": "card", "lines": lines})
        if self._frame is not None:
            try:
                self._frame.display.show_text("\n".join(lines))  # type: ignore[attr-defined]
            except Exception as exc:
                log.warning("[frame_sdk] show_card failed: %s", exc)

    def clear(self) -> None:
        self.sent.append({"kind": "clear"})
        if self._frame is not None:
            try:
                self._frame.display.clear()  # type: ignore[attr-defined]
            except Exception as exc:
                log.warning("[frame_sdk] clear failed: %s", exc)
