# First Device Test Plan

Run this checklist the first time a real Halo unit is available.

## 0. Pre-flight (host machine)

- [ ] `pip install brilliant-ble brilliant-msg`
- [ ] Confirm `brilliant_msg.MessageKind.FILE_WRITE` constant name matches SDK
- [ ] Note Halo BLE address from Brilliant companion app or iOS BLE scanner

## 1. Connection

```python
from dreamlayer.bridge.real_bridge import RealBridge
b = RealBridge(address="XX:XX:XX:XX:XX:XX")   # or None for auto-scan
info = b.connect()
print(info)   # expect {"device": "halo", "fw": "...", "lua": "5.3", "mock": False}
```

- [ ] `connect()` returns without error
- [ ] `info["mock"]` is `False`
- [ ] Halo shows visual indicator of BLE connection

## 2. Lua app upload

```python
b.load_lua_app("../halo-lua")
```

- [ ] No upload exceptions
- [ ] Halo display shows DreamLayer ready state after autorun
- [ ] `main.lua` runs on device (check Halo log output)

## 3. Card rendering

```python
from dreamlayer.hud.cards import ALL_SAMPLES
for name, card in ALL_SAMPLES.items():
    b.send_card(card)
    input(f"Check {name} on Halo — press Enter")
```

- [ ] Each card renders correctly on 256x256 display
- [ ] Fonts readable; confidence dot visible
- [ ] Privacy card shows muted colours

## 4. Privacy long-press

- [ ] Long-press physical button on Halo
- [ ] Host receives `privacy_pause` event via `_on_inbound`
- [ ] `b._paused` becomes `True`
- [ ] Content cards are dropped; only `PrivacyVeilCard` passes through
- [ ] Second long-press resumes capture

## 5. Full orchestrator smoke test

```python
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.bridge.real_bridge import RealBridge
o = Orchestrator(RealBridge())
info = o.boot("../halo-lua")
print("Booted:", info)
o.ingest_scene({"place":{"name":"Desk","signature":"desk_home"},"object":{"name":"Charger","near":"Blue mug"},"last_seen":"Just now","confidence":0.9})
card = o.ask("where is my charger")
print("Card:", card)
```

- [ ] Scene ingestion saves to DB
- [ ] Ask returns `ObjectRecallCard` with `primary == "Charger"`
- [ ] Card appears on Halo display

## 6. Calibration TODOs to resolve on device day

- MTU fragmentation: tune in `real_bridge._async_upload` and `_send_raw`
- `MessageKind.FILE_WRITE` — verify exact API name
- Halo display colour profile — adjust theme hex values if needed
- `get_device_info()` response keys — update `_async_connect` parsing
