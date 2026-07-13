# DreamLayer — Architecture

## System overview
DreamLayer is a **host-driven** stack. The phone/host runs intelligence and the
memory engine; Halo renders cards and emits input events over BLE.

```
+------------------+        BLE         +-----------------------+
|   Host (Python   | <----------------> |   Halo (Lua 5.3 VM)   |
|   / phone app)   |   typed messages   |   main.lua + modules  |
|                  |                    |                       |
|  memory engine   |   cards / commands |  state machine        |
|  pipelines       |   events / acks    |  display renderer      |
|  orchestrator    |                    |  capture stubs        |
+------------------+                    +-----------------------+
```

## Module boundaries
- **halo-lua/** owns rendering, input, capture triggers, and on-device state.
- **host-python/** owns memory, retrieval, summarization, intent, answer building,
  and emulator/real-device bridging.
- Communication crosses a **typed message protocol** (`ble/message_types.lua` and
  `bridge/*.py`). Neither side calls undocumented Halo APIs directly.

## Data flow (recall)
1. Capture (mock) → memory engine stores structured memory (not raw media by default)
2. User input event on Halo → host orchestrator builds intent
3. Memory engine retrieves + scores + summarizes
4. Host emits a **card payload** over BLE
5. Halo renderer draws the card with a soft transition

## Host/device split
- Heavy logic, embeddings, DB → host
- Glanceable rendering, input, low-latency state → device
- This keeps the Lua app small and deterministic.

## Emulator-first strategy
`emulator_bridge.py` drives `halo-emulator` (Lua runtime + virtual framebuffer +
event injection + screenshot export). Everything is testable headless.

## Future real-device path
`real_bridge.py` implements the same `BridgeBase` interface over `brilliant-ble` /
`brilliant-msg`. Swapping bridges should require **no** changes to the orchestrator.
