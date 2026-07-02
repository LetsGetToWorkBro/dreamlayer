# halo-lua — the Halo display client

The code that runs **on the Brilliant Labs Halo glasses**: the eyes and the
HUD. It captures sensor data, hands it to the phone hub over BLE, and renders
the cards the hub sends back — the on-glass half of DreamLayer.

> The thinking happens on the phone (and, when paired, the Mac mini Brain); the
> glasses capture and draw. Product overview: [`../README.md`](../README.md).

## Layout

```
main.lua            entry point — boots the client and the frame loop
app/                the on-glass app
  state_machine.lua  modes & transitions
  card_queue.lua     what's shown, and when
  figment_stage.lua  fixed Reality Compiler stages
  imu_gesture.lua    taps, double-taps, dwell — the input grammar
  events.lua · commands.lua · session.lua
ble/                the link to the phone hub
  protocol.lua · message_types.lua · host_comm.lua · telemetry.lua
capture/            sensors: camera · microphone · activity · scheduler
display/            the HUD — the visual system
  renderer.lua · cards.lua · layout.lua · typography.lua · palette.lua
  focus.lua · transitions.lua · animations.lua · materials.lua
  prism.lua · palette_cycle.lua · dream_renderer.lua   (Atmosphere)
lib/                json · queue · easing · constants · utils
system/             power · settings · time · logging
compat/             frame_adapter.lua — hardware shims
```

## Parity with the engine

The HUD's motion and palette are the **source of truth** the phone mirrors, not
the other way round — timings in `display/animations.lua` and colors in
`display/palette.lua` are echoed by the phone app
([`../phone-app/src/ui/theme/`](../phone-app/src/ui/theme/)) so the two screens
read as one product. If a value changes here, change it there too. The Cinema
v2 visual language is documented in [`../docs/`](../docs/) (`HUD_DESIGN_SYSTEM.md`,
`cinema_v2/`).

## Testing

The rendering and protocol logic is exercised from the Python suite via `lupa`
(Lua embedded in Python) — see `host-python/src/dreamlayer/tests/`. Run it with
`cd ../host-python && python -m pytest -q`.
