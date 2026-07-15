"""
Real Halo bridge over BLE using `brilliant-ble` + `brilliant-msg`.
Install: pip install brilliant-ble brilliant-msg

MessageKind constants are resolved at import time via runtime inspection
of the installed brilliant-msg package so we never assume a constant name.
"""
from __future__ import annotations
import asyncio
import json
import threading
from .base import BridgeBase
from .lua_loader import collect_lua

try:
    from brilliant_ble import BrilliantBLE           # type: ignore
    from brilliant_msg import Message, MessageKind   # type: ignore
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    BrilliantBLE = None  # type: ignore
    Message = None       # type: ignore
    MessageKind = None   # type: ignore

# ---------------------------------------------------------------------------
# MessageKind constant resolution
# We inspect the real enum at import time so a wrong assumed name causes an
# immediate, clear error rather than an AttributeError buried in the upload
# sequence.  Falls back to None when SDK is not installed.
# ---------------------------------------------------------------------------
_MKIND_MEMBERS: dict[str, object] = (
    {k: v for k, v in MessageKind.__members__.items()}
    if _SDK_AVAILABLE and MessageKind is not None
    else {}
)


def _resolve_kind(name: str, *fallbacks: str) -> object:
    """Return the first MessageKind member found in the priority list.

    Raises RuntimeError with the full available member list if none match,
    so the developer knows exactly what to use.
    """
    for candidate in (name, *fallbacks):
        if candidate in _MKIND_MEMBERS:
            return _MKIND_MEMBERS[candidate]
    available = ", ".join(sorted(_MKIND_MEMBERS.keys())) or "(SDK not installed)"
    raise RuntimeError(
        f"brilliant-msg has no MessageKind matching {[name, *fallbacks]}.\n"
        f"Available members: {available}\n"
        "Update _resolve_kind() call in real_bridge.py to match."
    )


# Resolve once at module load — fails fast with a clear message if wrong.
_KIND_FILE_WRITE: object = (
    _resolve_kind("FILE_WRITE", "FILE", "WRITE_FILE", "LUA_FILE")
    if _SDK_AVAILABLE else None
)
_KIND_COMMAND: object = (
    _resolve_kind("COMMAND", "CMD", "CONTROL")
    if _SDK_AVAILABLE else None
)
_KIND_DATA: object = (
    _resolve_kind("DATA", "PAYLOAD", "MESSAGE")
    if _SDK_AVAILABLE else None
)

# Maximum BLE payload bytes sent per Message.  If brilliant-msg does NOT
# handle MTU segmentation internally we chunk manually.
_MTU_PAYLOAD_BYTES = 128

# Largest frame the device-side reassembler accepts (halo-lua/ble/protocol.lua
# MAX_FRAME) — refuse to send anything the glasses would drop.
_MAX_FRAME_BYTES = 16384


def frame_payload(obj: dict) -> bytes:
    """JSON-encode obj with the on-wire framing ble/protocol.lua reassembles.

    Every frame — regardless of size — carries the 4-byte big-endian
    total-length header, and the total INCLUDES the header itself
    (lockstep with protocol.lua M.frame and reality_compiler.v2.transport).
    A headerless "small frame" shape does not exist on this wire.
    """
    body = json.dumps(obj, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    total = len(body) + 4
    if total > _MAX_FRAME_BYTES:
        raise ValueError(
            f"frame of {total} bytes exceeds device MAX_FRAME "
            f"({_MAX_FRAME_BYTES}); split the payload"
        )
    return total.to_bytes(4, "big") + body


def chunk_frame(framed: bytes, chunk_size: int = _MTU_PAYLOAD_BYTES) -> list[bytes]:
    """Split a framed payload into MTU-sized chunks for transmission."""
    return [framed[i:i + chunk_size] for i in range(0, len(framed), chunk_size)]


class HardwareNotConnectedError(RuntimeError):
    pass


class RealBridge(BridgeBase):
    def __init__(self, address: str | None = None, scan_timeout: float = 10.0) -> None:
        super().__init__()
        self.address = address
        self.scan_timeout = scan_timeout
        self._client = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._bundle: dict[str, str] = {}
        # Privacy gate state — initialised here, updated via _on_inbound
        self._paused: bool = False
        self._paused_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Async helpers
    # ------------------------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop and self._loop.is_running():
            return self._loop
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="dreamlayer-ble"
        )
        self._thread.start()
        return self._loop

    def _run(self, coro):
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=self.scan_timeout + 5)

    # ------------------------------------------------------------------
    # Connect / disconnect
    # ------------------------------------------------------------------

    def connect(self) -> dict:
        if not _SDK_AVAILABLE:
            raise ImportError(
                "brilliant-ble not installed. Run: pip install brilliant-ble brilliant-msg"
            )
        return self._run(self._async_connect())

    async def _async_connect(self) -> dict:
        ble = BrilliantBLE()
        device = await ble.find_device(
            address=self.address, timeout=self.scan_timeout
        )
        if device is None:
            raise HardwareNotConnectedError(
                f"No Halo found after {self.scan_timeout}s scan. "
                "Ensure Halo is powered on and in pairing range."
            )
        self._client = await ble.connect(device)
        self._client.on_message(self._on_inbound)
        self.address = device.address
        info = await self._client.get_device_info()
        return {
            "device":  info.get("name", "halo"),
            "address": self.address,
            "fw":      info.get("firmware_version"),
            "display": [256, 256],
            "lua":     info.get("lua_version", "5.3"),
            "mock":    False,
        }

    def disconnect(self) -> None:
        if self._client:
            self._run(self._client.disconnect())
            self._client = None

    # ------------------------------------------------------------------
    # Lua upload with post-upload verification
    # ------------------------------------------------------------------

    def load_lua_app(self, lua_root: str) -> None:
        """Collect, upload, verify, then reset the device.

        Verification step: after uploading all files, query the device file
        listing and assert main.lua is present at root before issuing reset.
        Raises FileNotFoundError with the actual listing if it is missing.
        """
        self._bundle = collect_lua(lua_root)
        if not self._client:
            raise HardwareNotConnectedError("Call connect() before load_lua_app()")
        self._run(self._async_upload())

    async def _async_upload(self) -> None:
        # 1. Upload all files
        for path, src in self._bundle.items():
            msg = Message(kind=_KIND_FILE_WRITE, path=path, content=src)
            await self._client.send(msg)

        # 2. Verify main.lua is present on the device before reset
        await self._assert_main_lua_present()

        # 3. Issue reset so the device autoruns main.lua
        reset_msg = Message(kind=_KIND_COMMAND, command="reset")
        await self._client.send(reset_msg)

    async def _assert_main_lua_present(self) -> None:
        """Query device file listing and assert main.lua exists at root.

        If the device exposes a list_files command, use it.  If not, skip
        with a warning — the caller will see a boot failure instead.
        """
        try:
            list_msg = Message(kind=_KIND_COMMAND, command="list_files")
            await self._client.send(list_msg)
            # Allow up to 3 s for the listing response
            response = await asyncio.wait_for(
                self._client.receive(), timeout=3.0
            )
            if response is None:
                print(
                    "[real_bridge] WARNING: list_files returned no response — "
                    "cannot verify main.lua presence. Proceeding with reset."
                )
                return
            # Response may be bytes, str, or dict depending on SDK version
            if isinstance(response, (bytes, bytearray)):
                response = response.decode()
            if isinstance(response, str):
                try:
                    response = json.loads(response)
                except json.JSONDecodeError:
                    pass

            # Normalise to a flat list of path strings
            if isinstance(response, dict):
                files: list[str] = response.get("files", [])
            elif isinstance(response, list):
                files = [str(f) for f in response]
            else:
                files = [str(response)]

            # Accept both "main.lua" and "/main.lua"
            normalised = [f.lstrip("/") for f in files]
            if "main.lua" not in normalised:
                raise FileNotFoundError(
                    "Upload verification failed: main.lua not found on device "
                    "after upload.\n"
                    f"Device file listing: {files}\n"
                    "Possible causes:\n"
                    "  • FILE_WRITE path prefix mismatch (check lua_loader.py)"
                    "  • Device storage write failure\n"
                    "  • list_files response format changed (check SDK release notes)"
                )
        except (NotImplementedError, AttributeError, asyncio.TimeoutError) as exc:
            # Device does not support list_files — degrade gracefully
            print(
                f"[real_bridge] WARNING: upload verification skipped ({type(exc).__name__}: {exc}). "
                "Cannot confirm main.lua is on device before reset."
            )

    # ------------------------------------------------------------------
    # Send helpers — with MTU chunking
    # ------------------------------------------------------------------

    def send_command(self, kind: str, payload: dict | None = None) -> None:
        self._require_connected()
        msg = {"t": "command", "kind": kind, "payload": payload or {}}
        self._run(self._send_raw(msg))

    def send_card(self, payload: dict, event: str = "answer_ready") -> None:
        self._require_connected()
        with self._paused_lock:
            paused = self._paused
        if paused and payload.get("type") != "PrivacyVeilCard":
            return
        msg = {"t": "card", "payload": payload, "event": event}
        self._run(self._send_raw(msg))

    def send_raw(self, obj: dict) -> None:
        """Send a raw dream/ambient frame (palette / geometry / line_field /
        sprite / sprite_avatar / dream_enter / dream_exit).

        Privacy gate: while paused, only mode-control frames pass — palette
        and sprite frames derive from live mic/camera signal and must never
        cross the pause boundary (mirrors emulator_bridge.send_raw).
        """
        from .base import pause_allows_raw
        self._require_connected()
        with self._paused_lock:
            paused = self._paused
        if paused and not pause_allows_raw(obj):
            return
        self._run(self._send_raw(obj))

    async def _send_raw(self, obj: dict) -> None:
        """Frame obj (4-byte length header, always) and send over BLE,
        chunking at _MTU_PAYLOAD_BYTES.

        brilliant-msg may handle fragmentation internally.  We chunk
        conservatively here so the Lua protocol.lua length-prefix reassembly
        layer is exercised and we never silently truncate large payloads.
        The header is mandatory on every frame: protocol.lua implements one
        reassembly shape, and a headerless small frame would be misread as
        a garbage length and wedge the link.
        """
        for chunk in chunk_frame(frame_payload(obj)):
            msg = Message(kind=_KIND_DATA, payload=chunk)
            await self._client.send(msg)

    # ------------------------------------------------------------------
    # Inbound event handling
    # ------------------------------------------------------------------

    def inject_event(self, name: str, payload: dict | None = None) -> None:
        command_map = {
            "privacy_pause":   ("pause",  None),
            "privacy_resume":  ("resume", None),
            "wake":            ("wake",   None),
        }
        if name in command_map:
            kind, p = command_map[name]
            # Reflect a host-initiated veil LOCALLY and immediately, before the
            # command even goes out — do not wait for the device to echo the
            # event back (audit 2026-07-14). In the round-trip window the old
            # code still delivered content cards through send_card, so the
            # transport-level veil lagged the wearer's gesture; the emulator
            # already flipped synchronously, so the two bridges disagreed.
            if name == "privacy_pause":
                with self._paused_lock:
                    self._paused = True
            elif name == "privacy_resume":
                with self._paused_lock:
                    self._paused = False
            self.send_command(kind, p)
        else:
            raise NotImplementedError(
                f"inject_event('{name}') has no real-device equivalent. "
                "Hardware emits real events; trigger the physical action instead."
            )

    def _on_inbound(self, raw) -> None:
        try:
            obj = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            name    = obj.get("name") or obj.get("t", "unknown")
            # telemetry (t="TEL") and figment events carry their fields at
            # the top level, not under "payload" — pass them through so the
            # orchestrator sees event/method/id/tag
            payload = obj.get("payload") or \
                {k: v for k, v in obj.items() if k not in ("name", "t")}
            # Update privacy gate — thread-safe
            if name == "privacy_pause":
                with self._paused_lock:
                    self._paused = True
            elif name == "privacy_resume":
                with self._paused_lock:
                    self._paused = False
            self._emit_event(name, payload)
        except Exception as exc:
            # Do NOT echo the raw frame back into the event stream. Inbound
            # frames can be signal-derived (mic/camera telemetry), and a PARSE
            # FAILURE must not leak the unparsed bytes to every event listener.
            # Emit an error marker only — the exception type, never the payload
            # (privacy hardening 2026-07-15).
            self._emit_event("parse_error", {"error": type(exc).__name__})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_connected(self) -> None:
        if not self._client:
            raise HardwareNotConnectedError("Not connected. Call connect() first.")
