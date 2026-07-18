# Maestro E2E flows

[Maestro](https://maestro.dev/) drives the **real** app on a device/emulator —
the layer jest can't reach (camera permission, capture, on-screen render).

## Run locally

```bash
# 1. install Maestro (once)
curl -Ls https://get.maestro.mobile.dev | bash

# 2. build + install a debug build on a running emulator/device
cd phone-app
npx expo run:android        # or: npx expo run:ios

# 3. run the flows
maestro test .maestro/
```

## Flows

- `look_smoke.yaml` — open the Look tab, grant the camera, capture, and confirm
  the world-lens screen answers without crashing.

Selectors track `src/i18n/translations.ts` (en) and `app/look.tsx`; update them
together if the copy or the screen changes.

## CI

`.github/workflows/maestro.yml` runs these on an Android emulator, but as a
**manual** (`workflow_dispatch`) job — the APK build + emulator boot is slow and
emulator E2E is flakier than a unit run, so it is not a PR gate. Promote it to a
nightly `schedule` once it's proven stable on your runners.
