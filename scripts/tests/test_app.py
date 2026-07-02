"""
pytest tests for dreamlayer/app.py.
All pure — no BLE hardware, no real network.
Bleak is mocked so tests run anywhere.
"""
from __future__ import annotations

import asyncio
import json
import struct
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from dreamlayer.app import (
    AppConfig,
    DreamLayerApp,
    _decode_frame,
    _encode_frame,
    _scan_for_halo,
    HALO_NAME_PREFIX,
)
from dreamlayer.fsm import Event, MemoryCard, State


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
) -> DreamLayerApp:
    cfg = AppConfig(
        device_address=device_address,
        loading_timeout=loading_timeout,
        reconnect_base=0.01,
        reconnect_max=0.05,
        reconnect_tries=1,
        log_level="WARNING",
    )
    return DreamLayerApp(config=cfg, on_loading=on_loading)


def _make_app_no_autoload(**kwargs) -> DreamLayerApp:
    """No on_loading → FSM stays at LISTENING after single-click."""
    return _make_app(on_loading=None, **kwargs)


def _mock_device(address: str, device_name: str, rssi: int) -> MagicMock:
    """
    Build a fake BLE device mock.

    IMPORTANT: MagicMock(name=...) sets the *mock's internal label*, not the
    .name attribute.  Always create the mock first, then assign .name and
    .address as plain attributes so the name-filter in _scan_for_halo works.
    """
    d = MagicMock()
    d.name    = device_name   # plain string attribute — filter reads this
    d.address = address
    d.rssi    = rssi
    return d


# ---------------------------------------------------------------------------
# Frame encoding / decoding
# ---------------------------------------------------------------------------

class TestFrameCodec:
    def test_encode_length_prefix(self):
        frame = _encode_frame({"t": "connect"})
        assert struct.unpack(">I", frame[:4])[0] == len(frame)

    def test_encode_decode_roundtrip(self):
        msg = {"t": "card", "payload": {"type": "ObjectRecallCard", "object": "KEYS"}}
        assert _decode_frame(_encode_frame(msg)) == msg

    def test_decode_too_short(self):
        assert _decode_frame(b"\x00\x01") is None

    def test_decode_invalid_json(self):
        assert _decode_frame(struct.pack(">I", 8) + b"not json") is None

    def test_encode_button_frame(self):
        assert _decode_frame(_encode_frame({"t": "button", "kind": "single"})) == {
            "t": "button", "kind": "single"
        }


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
        assert AppConfig(device_address="AA:BB:CC:DD:EE:FF").device_address == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# DreamLayerApp construction
# ---------------------------------------------------------------------------

class TestAppInit:
    def test_starts_disconnected(self):
        assert _make_app().state == State.DISCONNECT

    def test_fsm_accessible(self):
        assert _make_app().fsm is not None

    def test_default_config_used_when_none(self):
        assert DreamLayerApp().config.reconnect_base == 1.0

    def test_stop_before_run_safe(self):
        _make_app().stop()


# ---------------------------------------------------------------------------
# _on_rx — RX notification handler
# ---------------------------------------------------------------------------

class TestOnRx:
    def _app(self):
        app = _make_app_no_autoload()
        app._fsm.send(Event.BLE_CONNECT)
        return app

    def test_button_single_reaches_listening(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "button", "kind": "single"}))
        assert app.state == State.LISTENING

    def test_button_single_with_on_loading_reaches_loading(self):
        """With on_loading set, FSM auto-advances LISTENING → LOADING."""
        async def fake_ai(a): pass
        app = _make_app(on_loading=fake_ai)
        app._fsm.send(Event.BLE_CONNECT)
        app._on_rx(None, _make_frame({"t": "button", "kind": "single"}))
        assert app.state == State.LOADING

    def test_button_double_idle(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "button", "kind": "double"}))
        assert app.state == State.IDLE

    def test_button_long_enters_privacy(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "button", "kind": "long"}))
        assert app.state == State.PRIVACY_VEIL

    def test_imu_tap_ignored_in_idle(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "imu_tap"}))
        assert app.state == State.IDLE

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
        app._fsm.send(Event.BUTTON_LONG)
        app._on_rx(None, _make_frame({"t": "privacy_toggle"}))
        assert app.state == State.IDLE

    def test_unparseable_frame_ignored(self):
        app = self._app()
        app._on_rx(None, b"\x00")
        assert app.state == State.IDLE

    def test_unknown_type_ignored(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "unknown_event"}))
        assert app.state == State.IDLE

    def test_unknown_button_kind_ignored(self):
        app = self._app()
        app._on_rx(None, _make_frame({"t": "button", "kind": "quadruple"}))
        assert app.state == State.IDLE


# ---------------------------------------------------------------------------
# show_card
# ---------------------------------------------------------------------------

class TestShowCard:
    @pytest.mark.asyncio
    async def test_show_card_advances_fsm_to_card(self):
        app = _make_app()
        app._fsm.send(Event.BLE_CONNECT)
        app._fsm.send(Event.BUTTON_SINGLE)
        app._fsm.send(Event.LOADING_START)
        assert app.state == State.LOADING

        mock_client = MagicMock()
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
        app._fsm.send(Event.BUTTON_SINGLE)
        app._fsm.send(Event.LOADING_START)
        await app.show_card(MemoryCard(card_type="LoadingCard", payload={}))
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
            await app.show_card(MemoryCard(
                card_type="ObjectRecallCard",
                payload={"object": "WALLET", "place": "DESK",
                         "last_seen": "1h", "confidence": 0.88}
            ))

        app = _make_app(on_loading=fake_ai)
        app._fsm.send(Event.BLE_CONNECT)
        app._fsm.send(Event.BUTTON_SINGLE)
        app._fsm.send(Event.LOADING_START)
        await app._run_loading()
        assert called == [True]
        assert app.state == State.CARD

    @pytest.mark.asyncio
    async def test_loading_timeout_sends_timeout_event(self):
        async def slow_ai(app):
            await asyncio.sleep(99)

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
        await app._run_loading()


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

        async def fake_sleep(s): delays.append(s)

        with patch("dreamlayer.app.asyncio.sleep", side_effect=fake_sleep):
            await app._backoff_sleep()
            await app._backoff_sleep()
            await app._backoff_sleep()

        assert delays == [1.0, 2.0, 4.0]

    @pytest.mark.asyncio
    async def test_backoff_capped_at_max(self):
        app = _make_app()
        app.config.reconnect_max = 5.0
        app._reconnect_delay     = 4.0
        delays = []

        async def fake_sleep(s): delays.append(s)

        with patch("dreamlayer.app.asyncio.sleep", side_effect=fake_sleep):
            await app._backoff_sleep()
            await app._backoff_sleep()

        assert delays == [4.0, 5.0]


# ---------------------------------------------------------------------------
# Scan helper
#
# BleakScanner is module-level in app.py — patch it directly.
#
# GOTCHA: MagicMock(name="Frame v1") sets the mock's *internal label*, not
# the .name attribute.  Use _mock_device() which sets .name after construction.
# ---------------------------------------------------------------------------

class TestScanForHalo:
    @pytest.mark.asyncio
    async def test_returns_highest_rssi_halo(self):
        """Two Frame devices + one non-Frame; highest RSSI Frame wins."""
        d1 = _mock_device("AA:BB:CC:DD:EE:01", "Frame v1", rssi=-60)
        d2 = _mock_device("AA:BB:CC:DD:EE:02", "Frame v2", rssi=-45)
        d3 = _mock_device("AA:BB:CC:DD:EE:03", "Phone",    rssi=-30)

        mock_scanner = MagicMock()
        mock_scanner.discover = AsyncMock(return_value=[d1, d2, d3])

        with patch("dreamlayer.app.BleakScanner", mock_scanner):
            result = await _scan_for_halo(5.0)

        # "Phone" filtered; d2 RSSI=-45 beats d1 RSSI=-60
        assert result == "AA:BB:CC:DD:EE:02"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_halos(self):
        """No Frame-prefixed devices → returns None."""
        d1 = _mock_device("AA:BB:CC:DD:EE:01", "Phone",   rssi=-30)
        d2 = _mock_device("AA:BB:CC:DD:EE:02", "AirPods", rssi=-50)

        mock_scanner = MagicMock()
        mock_scanner.discover = AsyncMock(return_value=[d1, d2])

        with patch("dreamlayer.app.BleakScanner", mock_scanner):
            result = await _scan_for_halo(5.0)

        assert result is None

    @pytest.mark.asyncio
    async def test_single_halo_returned(self):
        d = _mock_device("AA:BB:CC:DD:EE:FF", "Frame glasses", rssi=-55)
        mock_scanner = MagicMock()
        mock_scanner.discover = AsyncMock(return_value=[d])

        with patch("dreamlayer.app.BleakScanner", mock_scanner):
            result = await _scan_for_halo(5.0)

        assert result == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# Integration: FSM wired through app
# ---------------------------------------------------------------------------

class TestFSMIntegration:
    def test_full_happy_path_via_rx(self):
        """connect → single (no on_loading → LISTENING) → LOADING → CARD → dismiss"""
        app = _make_app_no_autoload()
        app._fsm.send(Event.BLE_CONNECT)
        assert app.state == State.IDLE

        app._on_rx(None, _make_frame({"t": "button", "kind": "single"}))
        assert app.state == State.LISTENING

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
        app = _make_app_no_autoload()
        app._fsm.send(Event.BLE_CONNECT)
        app._on_rx(None, _make_frame({
            "t": "card",
            "payload": {"type": "SavedMemoryCard", "primary": "test"}
        }))
        assert app.state == State.CARD
        app._on_rx(None, _make_frame({"t": "button", "kind": "long"}))
        assert app.state == State.PRIVACY_VEIL
        app._on_rx(None, _make_frame({"t": "button", "kind": "long"}))
        assert app.state == State.IDLE

    def test_disconnect_resets_fsm(self):
        app = _make_app_no_autoload()
        app._fsm.send(Event.BLE_CONNECT)
        app._on_rx(None, _make_frame({"t": "button", "kind": "long"}))
        assert app.state == State.PRIVACY_VEIL
        app._fsm.send(Event.BLE_DISCONNECT)
        assert app.state == State.DISCONNECT
        assert app.fsm.ctx.privacy_active is False
