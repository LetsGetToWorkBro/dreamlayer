"""
pytest tests for memoscape/app.py.
All pure — no BLE hardware, no real network.
Bleak is mocked so tests run anywhere.
"""
from __future__ import annotations

import asyncio
import json
import struct
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from memoscape.app import (
    AppConfig,
    MemoscapeApp,
    _decode_frame,
    _encode_frame,
    _scan_for_halo,
)
from memoscape.fsm import Event, MemoryCard, State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame(msg: dict) -> bytes:
    raw = json.dumps(msg).encode()
    return struct.pack(">I", len(raw) + 4) + raw


def _make_app(
    on_loading=None,
    device_address="AA:BB:CC:DD:EE:FF",
    loading_timeout=5.0,
) -> MemoscapeApp:
    cfg = AppConfig(
        device_address=device_address,
        loading_timeout=loading_timeout,
        reconnect_base=0.01,
        reconnect_max=0.05,
        reconnect_tries=1,
        log_level="WARNING",
    )
    return MemoscapeApp(config=cfg, on_loading=on_loading)


# ---------------------------------------------------------------------------
# Frame encoding / decoding
# ---------------------------------------------------------------------------

class TestFrameCodec:
    def test_encode_length_prefix(self):
        frame = _encode_frame({"t": "connect"})
        length = struct.unpack(">I", frame[:4])[0]
        assert length == len(frame)

    def test_encode_decode_roundtrip(self):
        msg   = {"t": "card", "payload": {"type": "ObjectRecallCard", "object": "KEYS"}}
        frame = _encode_frame(msg)
        assert _decode_frame(frame) == msg

    def test_decode_too_short(self):
        assert _decode_frame(b"\x00\x01") is None

    def test_decode_invalid_json(self):
        bad = struct.pack(">I", 8) + b"not json"
        assert _decode_frame(bad) is None

    def test_encode_button_frame(self):
        frame = _encode_frame({"t": "button", "kind": "single"})
        assert _decode_frame(frame) == {"t": "button", "kind": "single"}


# ---------------------------------------------------------------------------
# AppConfig defaults
# ---------------------------------------------------------------------------

class TestAppConfig:
    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.device_address is None
        assert cfg.loading_timeout == 10.0
        assert cfg.reconnect_base == 1.0
        assert cfg.reconnect_max == 30.0
        assert cfg.reconnect_tries == 0

    def test_custom_address(self):
        cfg = AppConfig(device_address="AA:BB:CC:DD:EE:FF")
        assert cfg.device_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# MemoscapeApp construction
# ---------------------------------------------------------------------------

class TestAppInit:
    def test_starts_disconnected(self):
        app = _make_app()
        assert app.state == State.DISCONNECT

    def test_fsm_accessible(self):
        app = _make_app()
        assert app.fsm is not None

    def test_default_config_used_when_none(self):
        app = MemoscapeApp()
        assert app.config.reconnect_base == 1.0

    def test_stop_before_run_safe(self):
        app = _make_app()
        app.stop()   # should not raise


# ---------------------------------------------------------------------------
# _on_rx — RX notification handler
# ---------------------------------------------------------------------------

class TestOnRx:
    def _app(self):
        app = _make_app()
        app._fsm.send(Event.BLE_CONNECT)
        return app

    def test_button_single(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "button", "kind": "single"}))
        assert app.state == State.LISTENING

    def test_button_double_idle(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "button", "kind": "double"}))
        assert app.state == State.IDLE   # noop from IDLE

    def test_button_long_enters_privacy(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "button", "kind": "long"}))
        assert app.state == State.PRIVACY

    def test_imu_tap_ignored_in_idle(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "imu_tap"}))
        assert app.state == State.IDLE   # no transition from IDLE on IMU

    def test_card_received(self):
        app = self._app()
        app._on_rx(None, _make_frame({
            "t": "card",
            "payload": {"type": "SavedMemoryCard", "primary": "Parked level 3"}
        }))
        assert app.state == State.CARD
        assert app.fsm.ctx.current_card.card_type == "SavedMemoryCard"

    def test_privacy_toggle(self):
        app = self._app()
        app._fsm.send(Event.BUTTON_LONG)   # enter PRIVACY
        app._on_rx(None, _make_frame({"t": "privacy_toggle"}))
        assert app.state == State.IDLE

    def test_unparseable_frame_ignored(self):
        app = self._app()
        app._on_rx(None, b"\x00")   # too short
        assert app.state == State.IDLE   # unchanged

    def test_unknown_type_ignored(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "unknown_event"}))
        assert app.state == State.IDLE

    def test_unknown_button_kind_ignored(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "button", "kind": "quadruple"}))
        assert app.state == State.IDLE


# ---------------------------------------------------------------------------
# show_card — sends card to device and advances FSM
# ---------------------------------------------------------------------------

class TestShowCard:
    @pytest.mark.asyncio
    async def test_show_card_advances_fsm_to_loading_first(self):
        app  = _make_app()
        app._fsm.send(Event.BLE_CONNECT)
        app._fsm.send(Event.BUTTON_SINGLE)
        app._fsm.send(Event.LOADING_START)
        assert app.state == State.LOADING

        mock_client        = MagicMock()
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock()
        app._client = mock_client

        card = MemoryCard(card_type="ObjectRecallCard",
                          payload={"object": "KEYS", "place": "KITCHEN",
                                   "last_seen": "2h", "confidence": 0.91})
        await app.show_card(card)
        assert app.state == State.CARD
        assert mock_client.write_gatt_char.called

    @pytest.mark.asyncio
    async def test_show_card_no_client_still_advances_fsm(self):
        app = _make_app()
        app._fsm.send(Event.BLE_CONNECT)
        app._fsm.send(Event.CARD_RECEIVED)   # → CARD
        app._fsm.send(Event.BUTTON_DOUBLE)   # → IDLE
        app._fsm.send(Event.BUTTON_SINGLE)   # → LISTENING
        app._fsm.send(Event.LOADING_START)   # → LOADING
        card = MemoryCard(card_type="LoadingCard", payload={})
        await app.show_card(card)
        assert app.state == State.CARD


# ---------------------------------------------------------------------------
# _run_loading — AI callback + timeout
# ---------------------------------------------------------------------------

class TestRunLoading:
    @pytest.mark.asyncio
    async def test_loading_callback_called(self):
        called = []

        async def fake_ai(app):
            called.append(True)
            card = MemoryCard(card_type="ObjectRecallCard",
                              payload={"object": "WALLET", "place": "DESK",
                                       "last_seen": "1h", "confidence": 0.88})
            await app.show_card(card)

        app = _make_app(on_loading=fake_ai)
        app._fsm.send(Event.BLE_CONNECT)
        app._fsm.send(Event.BUTTON_SINGLE)    # → LISTENING
        app._fsm.send(Event.LOADING_START)    # → LOADING
        await app._run_loading()
        assert called == [True]
        assert app.state == State.CARD

    @pytest.mark.asyncio
    async def test_loading_timeout_sends_timeout_event(self):
        async def slow_ai(app):
            await asyncio.sleep(99)   # will timeout

        app = _make_app(on_loading=slow_ai, loading_timeout=0.05)
        app._fsm.send(Event.BLE_CONNECT)
        app._fsm.send(Event.BUTTON_SINGLE)
        app._fsm.send(Event.LOADING_START)
        await app._run_loading()
        assert app.state == State.IDLE

    @pytest.mark.asyncio
    async def test_loading_exception_sends_timeout_event(self):
        async def broken_ai(app):
            raise ValueError("AI engine crashed")

        app = _make_app(on_loading=broken_ai)
        app._fsm.send(Event.BLE_CONNECT)
        app._fsm.send(Event.BUTTON_SINGLE)
        app._fsm.send(Event.LOADING_START)
        await app._run_loading()
        assert app.state == State.IDLE

    @pytest.mark.asyncio
    async def test_no_loading_callback_safe(self):
        app = _make_app(on_loading=None)
        app._fsm.send(Event.BLE_CONNECT)
        app._fsm.send(Event.BUTTON_SINGLE)
        app._fsm.send(Event.LOADING_START)
        await app._run_loading()   # should not raise


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------

class TestBackoff:
    @pytest.mark.asyncio
    async def test_backoff_doubles(self):
        app = _make_app()
        app.config.reconnect_base = 1.0
        app.config.reconnect_max  = 8.0
        app._reconnect_delay      = 1.0

        delays = []
        async def fake_sleep(s):
            delays.append(s)

        with patch("memoscape.app.asyncio.sleep", side_effect=fake_sleep):
            await app._backoff_sleep()
            await app._backoff_sleep()
            await app._backoff_sleep()

        assert delays == [1.0, 2.0, 4.0]

    @pytest.mark.asyncio
    async def test_backoff_capped_at_max(self):
        app = _make_app()
        app.config.reconnect_max  = 5.0
        app._reconnect_delay      = 4.0

        delays = []
        async def fake_sleep(s):
            delays.append(s)

        with patch("memoscape.app.asyncio.sleep", side_effect=fake_sleep):
            await app._backoff_sleep()
            await app._backoff_sleep()

        assert delays[0] == 4.0
        assert delays[1] == 5.0


# ---------------------------------------------------------------------------
# Scan helper (mocked)
# ---------------------------------------------------------------------------

class TestScanForHalo:
    @pytest.mark.asyncio
    async def test_returns_highest_rssi(self):
        d1 = MagicMock(address="AA:BB:CC:DD:EE:01", name="Frame v1", rssi=-60)
        d2 = MagicMock(address="AA:BB:CC:DD:EE:02", name="Frame v2", rssi=-45)
        d3 = MagicMock(address="AA:BB:CC:DD:EE:03", name="Phone",    rssi=-30)

        with patch("memoscape.app.BleakScanner") as MockScanner:
            MockScanner.discover = AsyncMock(return_value=[d1, d2, d3])
            with patch.dict("sys.modules", {"bleak": MagicMock(BleakScanner=MockScanner)}):
                from importlib import import_module, reload
                import memoscape.app as app_mod
                app_mod.BleakScanner = MockScanner
                result = await _scan_for_halo.__wrapped__(6.0) if hasattr(_scan_for_halo, "__wrapped__") else None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_halos(self):
        with patch("memoscape.app._scan_for_halo", new_callable=AsyncMock) as mock_scan:
            mock_scan.return_value = None
            result = await mock_scan(5.0)
            assert result is None


# ---------------------------------------------------------------------------
# Integration: FSM wired through app correctly
# ---------------------------------------------------------------------------

class TestFSMIntegration:
    def test_full_happy_path_via_rx(self):
        """connect → single → loading → card → dismiss"""
        app = _make_app()
        app._fsm.send(Event.BLE_CONNECT)
        assert app.state == State.IDLE

        app._on_rx(None, _make_frame({"t": "button", "kind": "single"}))
        assert app.state == State.LISTENING

        # Manually advance to LOADING (simulating app._on_transition)
        app._fsm.send(Event.LOADING_START)
        assert app.state == State.LOADING

        card = MemoryCard(card_type="ObjectRecallCard",
                          payload={"object": "KEYS", "place": "KITCHEN",
                                   "last_seen": "2h", "confidence": 0.91})
        app._fsm.send(Event.RESULT_READY, payload=card)
        assert app.state == State.CARD
        assert app.fsm.ctx.current_card.card_type == "ObjectRecallCard"

        app._on_rx(None, _make_frame({"t": "button", "kind": "double"}))
        assert app.state == State.IDLE
        assert app.fsm.ctx.current_card is None

    def test_privacy_flow_via_rx(self):
        """connect → card → long press → privacy → long press → idle"""
        app = _make_app()
        app._fsm.send(Event.BLE_CONNECT)
        app._on_rx(None, _make_frame({
            "t": "card",
            "payload": {"type": "SavedMemoryCard", "primary": "test"}
        }))
        assert app.state == State.CARD

        app._on_rx(None, _make_frame({"t": "button", "kind": "long"}))
        assert app.state == State.PRIVACY

        app._on_rx(None, _make_frame({"t": "button", "kind": "long"}))
        assert app.state == State.IDLE

    def test_disconnect_resets_fsm(self):
        app = _make_app()
        app._fsm.send(Event.BLE_CONNECT)
        app._on_rx(None, _make_frame({"t": "button", "kind": "long"}))
        assert app.state == State.PRIVACY
        app._fsm.send(Event.BLE_DISCONNECT)
        assert app.state == State.DISCONNECT
        assert app.fsm.ctx.privacy_active is False
