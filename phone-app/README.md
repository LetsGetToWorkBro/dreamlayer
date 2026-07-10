# DreamLayer — phone app

The DreamLayer hub: pair your glasses, Mac mini Brain, and cloud; ask your
brain from your pocket; and manage privacy — all from one Expo/React Native
app. The phone is the brain by default (works fully offline); connecting a Mac
mini is the upgrade.

## Run it

Requires Node 18+.

```bash
npm install
npx expo start
```

Scan the QR from the terminal with **Expo Go** (iOS: Camera → tap the banner;
Android: Expo Go → *Scan QR code*). Or press `w` for web, `i` / `a` for a
simulator/emulator.

## Pair the trio (one code)

1. On the **Mac Brain panel** (`python -m dreamlayer.ai_brain.server` — see
   [`../docs/TESTING.md`](../docs/TESTING.md)) → *Connections* → **Pair a phone**
   → **Copy code**.
2. In the app → **Brain** tab → **＋ Pair a device** → paste → **Connect**.

One `dreamlayer:…` code carries the Brain URL, token, and glasses id. The phone
decodes it with the same codec the Brain encodes with
([`src/services/pairing.ts`](src/services/pairing.ts) ↔
`host-python/.../pairing.py`, kept byte-for-byte compatible; the Python side
is covered by the host test suite).

## The three brain switches

- **Mac mini** — off by default (*phone is the brain*); connect it for a bigger
  local model + your indexed files.
- **Cloud** — its own switch: frontier reach for the hardest, non-personal asks.
  Nothing private ever leaves.
- **Incognito** — forces cloud off and pauses capture for the session.

## Layout

```
app/                 expo-router screens — five tabs + Labs
  brain.tsx          the hub (default tab): pairing, connections, cloud, incognito, ask
  now.tsx            live Halo mirror, morning brief, voice box, quick actions
  messages.tsx       Messages/Mail relay: suggested replies, approve-and-send
  memories.tsx       your recall, grouped by day (+ ask-your-files when paired)
  settings.tsx       every toggle: privacy, Juno, wake, Labs, danger zone
  rewind.tsx         (Labs) today's hour blocks from the Brain
  saga.tsx           (Labs) rank, XP, achievements
  profile.tsx        (Labs) what Juno knows about you
  rehearsal.tsx      (Labs) Reality Compiler v2 surface
  confluence.tsx     (Labs) two wearers, one entangled sky
  onboarding.tsx     first-run flow
src/
  state/             zustand stores (useBrainStore is the source of truth)
  services/          pairing codec, notifications, earcons, haptics
  ui/                the design system — see DESIGN.md
```

## Design system

Every screen composes from a shared primitive layer (`Screen`, `Card`,
`Tappable`, motion hooks). Read **[DESIGN.md](DESIGN.md)** before adding UI so
the app stays one cohesive, tactile surface.

## Type-check & test

```bash
npm install
npx tsc --noEmit
npm test            # two jest projects: "logic" (ts-jest) + "component" (jest-expo/RNTL)
```

## The glasses BLE link (dev build only)

The whole BLE stack — framing (`src/ble/framing.ts`, byte-parity with the
Python wire protocol), the reconnecting `HaloBridge` (`src/ble/bridge.ts`), and
`useGlassesStore` — is pure TypeScript over an injected transport, so it
unit-tests today and **Expo Go keeps working** (no transport attached → the demo
Halo pairs as before).

To drive a real Halo you need a native module, which means leaving Expo Go:

```bash
npx expo install react-native-ble-plx
# add to app.json:  "plugins": [["react-native-ble-plx", { "isBackgroundEnabled": true }]]
eas build --profile development --platform ios   # a dev client; Expo Go can't load native modules
```

Then attach the transport once at startup:

```ts
import { makeBlePlxTransport } from "./src/ble/transport.blePlx";
import { useGlassesStore } from "./src/state/useGlassesStore";
useGlassesStore.getState().attachTransport(makeBlePlxTransport());
```

The service/characteristic UUIDs in `transport.blePlx.ts` are placeholders —
fill them from the first bench-Halo session (the one thing that can't be known
without the device on a desk).
