# Puente → DreamLayer Live Translation Captions

Puente (the real-time earbud translation app) streams live transcript and
translation text to a DreamLayer host over a LAN WebSocket. DreamLayer
converts each event into a `LiveCaptionCard` and renders it on the Halo
glasses, so the wearer sees the conversation translated in real time.

```
┌─────────────┐   ws://host:8765    ┌──────────────────────┐   BLE card    ┌───────────┐
│  Puente app │ ──────────────────▶ │  DreamLayer host     │ ────────────▶ │   Halo    │
│  (phone)    │  partial/translation│  PuenteCaptionServer │  LiveCaption  │  glasses  │
│             │       frames        │  → PuenteBridge      │     Card      │           │
└─────────────┘                     └──────────────────────┘               └───────────┘
```

Puente deliberately does **not** write to the glasses' BLE Lua REPL when
DreamLayer is running — the halo-lua app owns the display and its card
queue. Routing through the host keeps captions inside DreamLayer's
priority/focus system (`LiveCaptionCard` renders at `CardQueue.CONTEXT`
priority via the generic layout-card path).

## Components

| Piece | Path |
|---|---|
| WebSocket ingress | `host-python/src/dreamlayer/orchestrator/puente_server.py` |
| Caption → card bridge | `host-python/src/dreamlayer/orchestrator/puente_bridge.py` |
| Card factory | `host-python/src/dreamlayer/hud/cards.py` (`live_caption_card`) |
| Runnable entry | `scripts/puente_live.py` |
| Tests | `host-python/src/dreamlayer/tests/test_puente_server.py` |
| Puente-side client | puente-app `services/dreamlayer/dreamlayerLink.ts` |

## Running

```bash
uv sync --extra puente          # installs websockets (bleak is a base dep)

uv run python scripts/puente_live.py            # auto-discover Halo over BLE
uv run python scripts/puente_live.py --dry-run  # no glasses — print cards
uv run python scripts/puente_live.py --device AA:BB:CC:DD:EE:FF --port 8765
```

The script prints the LAN URL to enter in the Puente app
(**Settings → DreamLayer Glasses → Host address**), e.g.
`ws://192.168.1.50:8765`. Toggle **Send captions to DreamLayer** on, and
every finalized translation (plus throttled in-flight partials) appears on
the glasses.

To embed the ingress in your own host process instead of the script:

```python
from dreamlayer.orchestrator.puente_bridge import PuenteBridge
from dreamlayer.orchestrator.puente_server import PuenteCaptionServer

bridge = PuenteBridge()
bridge.on_card(my_ble_bridge.send_card)   # any BridgeBase works

server = PuenteCaptionServer(bridge, port=8765)
await server.start()
```

## Wire protocol (v1)

JSON text frames over WebSocket. Client → server:

| Frame | Fields | Effect |
|---|---|---|
| `hello` | `v`, `client` | Replied with `hello_ack` |
| `partial` | `text`, `srcLang?`, `speaker?`, `confidence?` | Caption card, original only. Throttled server-side (300 ms) |
| `caption` | alias of `partial` | — |
| `translation` | `original`, `translation`, `srcLang?`, `targetLang?`, `confidence?`, `speaker?`, `turnId?` | Caption card with translation as the hero line. Replied with `ack` |
| `ping` | — | Replied with `pong` |

Server → client: `hello_ack`, `ack` (echoes `turnId` when supplied),
`pong`, and `error` (`reason`) for malformed frames. Text fields are
bounded at 512 chars; `confidence` is clamped to `[0, 1]`; unknown or
malformed optional fields are dropped rather than rejected.

When `srcLang` is omitted, `PuenteBridge` auto-detects ES vs EN with a
function-word heuristic and sets the caption's language pill accordingly.

## Notes

- Partials are throttled at both ends (250 ms client, 300 ms server) so a
  word-by-word reveal can't flood the BLE link; finalized translations
  always pass.
- `scripts/puente_live.py` keeps at most one pending card in its BLE queue —
  when the link is slower than the caption stream, stale intermediate
  captions are dropped and the newest wins.
- The `websockets` dependency is optional (`dreamlayer[puente]`);
  `puente_server.py` imports it lazily so the module and its tests work
  without it.
