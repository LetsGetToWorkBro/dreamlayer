"""Tests for PuenteCaptionServer — Puente WS frames → PuenteBridge → cards.

The transport-independent handle_message() path is exercised directly with
asyncio.run(), so these tests need neither the optional ``websockets``
dependency nor a network socket.
"""
import asyncio
import json

import pytest

from dreamlayer.orchestrator.puente_bridge import PuenteBridge
from dreamlayer.orchestrator.puente_server import (
    PROTOCOL_VERSION,
    PuenteCaptionServer,
    PuenteProtocolError,
    parse_puente_message,
)


# ---------------------------------------------------------------------------
# parse_puente_message
# ---------------------------------------------------------------------------

def test_parse_valid_translation():
    msg = parse_puente_message(json.dumps({
        "v": 1, "type": "translation",
        "original": "Hola mundo", "translation": "Hello world",
        "srcLang": "es", "confidence": 0.93, "turnId": "t-1",
    }))
    assert msg["type"] == "translation"
    assert msg["original"] == "Hola mundo"
    assert msg["confidence"] == 0.93

def test_parse_valid_partial_bytes():
    msg = parse_puente_message(json.dumps({"type": "partial", "text": "Hola"}).encode())
    assert msg["type"] == "partial"
    assert msg["text"] == "Hola"

def test_parse_caption_alias_accepted():
    msg = parse_puente_message(json.dumps({"type": "caption", "text": "Hola"}))
    assert msg["type"] == "caption"

def test_parse_rejects_invalid_json():
    with pytest.raises(PuenteProtocolError):
        parse_puente_message("{not json")

def test_parse_rejects_non_object():
    with pytest.raises(PuenteProtocolError):
        parse_puente_message("[1,2,3]")

def test_parse_rejects_unknown_type():
    with pytest.raises(PuenteProtocolError):
        parse_puente_message(json.dumps({"type": "selfdestruct"}))

def test_parse_rejects_empty_text():
    with pytest.raises(PuenteProtocolError):
        parse_puente_message(json.dumps({"type": "partial", "text": "   "}))

def test_parse_rejects_missing_translation_fields():
    with pytest.raises(PuenteProtocolError):
        parse_puente_message(json.dumps({"type": "translation", "original": "Hola"}))

def test_parse_clamps_confidence():
    msg = parse_puente_message(json.dumps(
        {"type": "partial", "text": "Hola", "confidence": 7.5}
    ))
    assert msg["confidence"] == 1.0

def test_parse_drops_malformed_optional_fields():
    msg = parse_puente_message(json.dumps(
        {"type": "partial", "text": "Hola", "speaker": 42, "confidence": "high"}
    ))
    assert "speaker" not in msg
    assert "confidence" not in msg

def test_parse_bounds_text_length():
    msg = parse_puente_message(json.dumps({"type": "partial", "text": "x" * 2000}))
    assert len(msg["text"]) == 512


# ---------------------------------------------------------------------------
# handle_message — replies + bridge dispatch
# ---------------------------------------------------------------------------

def _make_server(**kwargs):
    bridge = PuenteBridge()
    cards: list[dict] = []
    bridge.on_card(cards.append)
    server = PuenteCaptionServer(bridge, **kwargs)
    replies: list[dict] = []

    async def send(payload: str) -> None:
        replies.append(json.loads(payload))

    return server, cards, replies, send


def _handle(server, send, obj) -> dict | None:
    return asyncio.run(server.handle_message(json.dumps(obj), send))


def test_hello_gets_hello_ack():
    server, _cards, replies, send = _make_server()
    _handle(server, send, {"v": 1, "type": "hello", "client": "puente"})
    assert replies == [{"type": "hello_ack", "server": "dreamlayer", "v": PROTOCOL_VERSION}]

def test_ping_gets_pong():
    server, _cards, replies, send = _make_server()
    _handle(server, send, {"type": "ping"})
    assert replies == [{"type": "pong"}]

def test_invalid_frame_gets_error_reply():
    server, cards, replies, send = _make_server()
    asyncio.run(server.handle_message("{broken", send))
    assert replies[0]["type"] == "error"
    assert cards == []

def test_translation_produces_card_and_ack():
    server, cards, replies, send = _make_server()
    card = _handle(server, send, {
        "type": "translation",
        "original": "No te preocupes",
        "translation": "Don't worry",
        "srcLang": "es",
        "confidence": 0.91,
        "speaker": "Maria",
        "turnId": "t-7",
    })
    assert card["type"] == "LiveCaptionCard"
    assert card["original"] == "No te preocupes"
    assert card["translation"] == "Don't worry"
    assert card["primary"] == "Don't worry"
    assert "Maria" in card["eyebrow"]
    assert cards == [card]
    assert replies == [{"type": "ack", "turnId": "t-7"}]

def test_translation_ack_without_turn_id():
    server, _cards, replies, send = _make_server()
    _handle(server, send, {
        "type": "translation", "original": "Hola", "translation": "Hello",
    })
    assert replies == [{"type": "ack"}]

def test_partial_produces_card_without_ack():
    server, cards, replies, send = _make_server()
    card = _handle(server, send, {"type": "partial", "text": "Yo me encargo de esto"})
    assert card["type"] == "LiveCaptionCard"
    assert card["src_lang"] == "es"           # auto-detected
    assert card["translation"] == ""          # not translated yet
    assert cards == [card]
    assert replies == []


# ---------------------------------------------------------------------------
# Partial throttling
# ---------------------------------------------------------------------------

def test_partials_throttled_translations_not():
    now = [0.0]
    server, cards, _replies, send = _make_server(
        partial_min_interval_ms=300, clock=lambda: now[0],
    )

    _handle(server, send, {"type": "partial", "text": "Hola"})
    now[0] += 0.1  # 100ms later — inside the throttle window
    dropped = _handle(server, send, {"type": "partial", "text": "Hola mun"})
    assert dropped is None
    assert len(cards) == 1

    # A finalized translation always passes, even inside the window.
    _handle(server, send, {
        "type": "translation", "original": "Hola mundo", "translation": "Hello world",
    })
    assert len(cards) == 2

    now[0] += 0.4  # past the window — partials flow again
    _handle(server, send, {"type": "partial", "text": "Otra frase"})
    assert len(cards) == 3


# ---------------------------------------------------------------------------
# start() without the websockets package
# ---------------------------------------------------------------------------

def test_start_without_websockets_raises_helpful_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "websockets":
            raise ImportError("No module named 'websockets'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    server, _cards, _replies, _send = _make_server()
    with pytest.raises(RuntimeError, match="dreamlayer\\[puente\\]"):
        asyncio.run(server.start())
