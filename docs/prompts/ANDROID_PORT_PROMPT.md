# Prompt: Bring the DreamLayer phone app to Android (full parity with iOS)

> Paste everything below the line into a Claude (Fable 5) session opened on
> this repository. Best run in plan mode first: let it produce the plan, review
> it, then approve implementation.

---

You are working in the DreamLayer repository. Your task: make the phone app a
**first-class Android app** with complete feature, functionality, and UI/UX
parity with the existing iOS app, ready to ship on Google Play.

## The one fact that shapes everything

`phone-app/` is **Expo SDK 57 / React Native 0.86** with `expo-router`, the new
architecture enabled, and `react-native-web` already in the tree. This is NOT a
rewrite and you must not fork the codebase: it is one codebase that must run
beautifully on both platforms. Your job is to audit, enable, fix, and ship the
Android side without changing any iOS behavior.

## Ground truth to read first

- `phone-app/DESIGN.md` — the design contract. The UI is Mac OS 8.1
  "Platinum" (grey pinstripe desktop, beveled windows, Chicago titles via
  `assets/fonts/ChicagoFLF.ttf`, brand teal `#0B6B52`). Android must look
  **identical** to iOS, not "Material-adapted." Never swap in Material widgets.
- `phone-app/app/` — 24 expo-router routes: 5-tab bar (`_layout.tsx`), Now
  dashboard, Brain hub, Look (camera), Waypath, People, Memories, Rewind,
  Saga, Ember, Confluence, Labs, onboarding, settings, and more.
- `phone-app/app.json` — an `android` block already exists (package
  `com.letsgettoworkbro.dreamlayer`, adaptive icon). Extend it; don't rename.
- `phone-app/eas.json` + `package.json` scripts — currently iOS-only
  (`build:ios`, `submit:ios`, iOS-only submit profile).
- `phone-app/src/i18n/` — 9 locales with a catalog-parity gate; any new
  user-facing string lands in all of them.
- `phone-app/store/` + `phone-app/fastlane/` — the finished iOS App Store
  listing (copy, localized listings, screenshots, review notes). Mirror it for
  Play, reusing the copy.
- `.github/workflows/phone.yml` — the phone CI gate (Jest + typecheck).
- Existing `Platform.OS` branches (e.g. `app/_layout.tsx` tab-bar heights,
  `src/ui/components/HaloMirror.tsx` elevation, `Juno.tsx` glow) show the
  intended pattern for per-platform tuning.

## The work

### 1. Full-surface Android audit
Walk every route in `phone-app/app/` and every component in `phone-app/src/ui/`
on an Android emulator (use Demo Mode — it fills every screen with sample data,
no hardware needed). Fix what differs from iOS:

- **Shadows**: iOS `shadow*` styles render as nothing on Android — add
  `elevation` (or SVG/border-based bevels, which suit Platinum chrome better)
  everywhere depth matters.
- **Safe areas & insets**: tab-bar heights and paddings are hardcoded per
  platform in `_layout.tsx`; verify against Android gesture nav and
  edge-to-edge (SDK 57 defaults to edge-to-edge on Android — check status/nav
  bar treatment against the Platinum desktop background `#B8B8B8`).
- **Back handling**: hardware/gesture back must pop the router stack sanely on
  every drill-in (Brain hub → Labs/Preferences, Now → detail screens), and exit
  from the tab roots. Enable predictive back if it doesn't fight the design.
- **`expo-blur`**: blur on Android is approximate/experimental — verify every
  usage and provide a solid-color Platinum fallback where it looks wrong.
- **Fonts**: confirm ChicagoFLF and Space Grotesk load and measure identically;
  check for text clipping (Android measures text differently).
- **Haptics**: map `expo-haptics` calls to sensible Android amplitudes; no-op
  where the effect doesn't exist rather than buzzing harshly.
- **Audio**: the `assets/sounds/` cues via `expo-audio` — verify volume/ducking
  behavior on Android.
- **Keyboard**: check every input (pairing code, ask box) against Android
  keyboard resize/pan behavior; set `softwareKeyboardLayoutMode` if needed.

### 2. Android platform config (`app.json`)
- Adaptive icon: verify the foreground respects the safe zone against
  `backgroundColor` `#241F38`; add a monochrome layer for themed icons.
- Splash: confirm the splash config renders correctly with Android 12+
  SplashScreen APIs.
- Permissions: CAMERA (QR pairing — keep the same rationale string),
  POST_NOTIFICATIONS (see §4), and **nothing else**. DreamLayer's privacy
  posture is the product; do not let a library sneak in extra permissions —
  audit the final merged manifest and strip/blockedPermissions anything
  unneeded.
- Deep links: the `dreamlayer` scheme must open via Android intent filters
  (pairing links, lens share links).

### 3. LAN networking — the one real Android landmine
The phone talks to the Brain over plain HTTP on the LAN (`:7777`, token
header). Android blocks cleartext HTTP by default. Add a **network security
config** that permits cleartext **only** to private-range/LAN addresses —
do NOT set a blanket `usesCleartextTraffic=true`. Then verify end-to-end on
Android: QR pairing scan → token save → status polling → ask round-trip.
This is a privacy-sensitive change; keep it minimal and comment the config
with why it's scoped the way it is.

### 4. Notifications
`expo-notifications` on Android requires channels and (API 33+) a runtime
permission. Create named channels matching the product's voice (e.g. "Morning
brief", "Commitments"), request permission at the moment of first relevant use
(not app launch), set the small icon + accent color to match the brand, and
verify the brief notification fires in Demo Mode.

### 5. Build & submit pipeline
- `eas.json`: add Android to `development` (APK, internal), `preview` (APK),
  `production` (AAB, autoIncrement); add an Android submit profile using a
  Google service-account key path (documented, gitignored — mirror how
  `fastlane/asc_key.json` is handled for iOS).
- `package.json`: add `build:android`, `submit:android`.
- Extend `phone-app/SUBMIT.md` with the Play half: what's automated vs. what
  needs the owner's Google Play Console account (keystore/signing by EAS,
  service account creation, first manual upload), marked with the same 🔑
  convention as the iOS steps.
- Mirror the store listing: create `fastlane/supply` metadata (or
  `store/play-listing.md`) from `store/listing.md` + the 8 localizations,
  Play feature graphic, and a filled **Data safety** form draft — DreamLayer's
  honest answer is strong (no data collected/shared; everything on-device);
  source it from `landing/privacy.html` and say so in review notes.

### 6. Tests & CI
- Jest suite and typecheck stay green; add regression tests for anything you
  fix with a platform branch (the repo pattern: pure logic unit-tested).
- Extend `.github/workflows/phone.yml` if any Android-specific check is
  automatable (manifest permission audit is a good candidate: fail CI if the
  merged manifest gains a permission not on the allowlist).
- Update `DESIGN.md` with a short "Android notes" section documenting every
  deliberate per-platform deviation (there should be very few).

## Constraints (non-negotiable)

- One codebase. No forks, no `.android.tsx` file explosion — prefer small
  `Platform.select` branches in the existing style.
- iOS behavior and appearance unchanged. Every diff must be provably neutral
  for iOS (Jest + a visual pass in the iOS simulator).
- The privacy contract holds: no new permissions, no analytics, no network
  calls beyond the existing phone↔Brain/localhost patterns, cleartext scoped
  to LAN only.
- Localization parity: every new string in all 9 locales or the catalog gate
  fails the build.
- Platinum fidelity: if a component can't be made pixel-faithful on Android,
  redesign the implementation (SVG bevels, borders), not the design.

## Definition of done

1. `npx expo start --android` → every one of the 24 routes walked in Demo Mode
   looks and behaves like iOS (screenshot pairs for the tab roots as proof).
2. Real pairing flow works against a running Brain
   (`python -m dreamlayer.ai_brain.server --token test`) from the Android
   emulator over LAN.
3. `npm test` and `npm run typecheck` green; CI green.
4. `eas build --platform android --profile production` config validates
   (`npx expo-doctor`, `eas build:configure` clean).
5. Play listing assets and `SUBMIT.md` Android section complete enough that
   the only remaining steps are the 🔑 owner-account ones.

Work in review-sized commits (config, networking, UI parity, notifications,
store pipeline), each with tests where applicable.
