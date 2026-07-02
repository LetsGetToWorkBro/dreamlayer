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
`host-python/.../pairing.py`), verified byte-for-byte in the test suite.

## The three brain switches

- **Mac mini** — off by default (*phone is the brain*); connect it for a bigger
  local model + your indexed files.
- **Cloud** — its own switch: frontier reach for the hardest, non-personal asks.
  Nothing private ever leaves.
- **Incognito** — forces cloud off and pauses capture for the session.

## Layout

```
app/                 expo-router screens
  brain.tsx          the hub (default tab): connections, cloud, incognito, ask
  now.tsx            live Halo mirror + quick actions
  memories.tsx       your recall, grouped by day
  rehearsal.tsx      Reality Compiler v2 surface
  confluence.tsx     two wearers, one entangled sky
  settings.tsx       privacy + danger zone
  onboarding.tsx     first-run flow
src/
  state/             zustand stores (useBrainStore is the source of truth)
  services/          pairing codec
  ui/                the design system — see DESIGN.md
```

## Design system

Every screen composes from a shared primitive layer (`Screen`, `Card`,
`Tappable`, motion hooks). Read **[DESIGN.md](DESIGN.md)** before adding UI so
the app stays one cohesive, tactile surface.

## Type-check

```bash
npm install
npx tsc --noEmit
```
