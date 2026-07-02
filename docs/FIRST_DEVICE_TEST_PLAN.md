# DreamLayer — First Device Day Test Plan

Run top-to-bottom the moment Halo arrives. Log every result in the issue table.

## Pre-flight
- [ ] Charge Halo to >50%
- [ ] `pip install brilliant-ble brilliant-msg` in host env
- [ ] Confirm host BLE adapter on

## Bring-up checklist
1. [ ] **Pairing** — host discovers + bonds with Halo
2. [ ] **Device detection** — `real_bridge.connect()` returns device info
3. [ ] **Lua upload** — push `halo-lua/` bundle; confirm `main.lua` autoruns
4. [ ] **Hello world render** — render a single text line
5. [ ] **State machine boot** — boot→ready transition observed, ReadyCard shows
6. [ ] **Button events** — single / double / long-press reach state machine
7. [ ] **Paused state** — long-press shows PrivacyVeilCard; capture blocked
8. [ ] **Card rendering** — render all 11 card types via `export` parity check
9. [ ] **Camera probe** — single still capture round-trips
10. [ ] **Microphone probe** — short mic stream round-trips
11. [ ] **IMU probe** — tap event detected
12. [ ] **BLE latency** — measure card-send → on-screen latency (target <250ms)
13. [ ] **Readability** — verify legibility at all card sizes outdoors/indoors
14. [ ] **Battery** — log drain over a 10-min session

## Issue log
| # | Area | Severity | Notes | Status |
|---|------|----------|-------|--------|
|   |      |          |       |        |
