# DreamLayer — one-command-ish submission (what's automated vs. what only you can do)

Everything that *can* be prepared is prepared, for **both stores**. The steps below that need
**your Apple or Google account** are marked 🔑 — they authenticate as you and/or build a signed
binary, which cannot be done from a shared/CI Linux box on your behalf.

## What's already done (in the repo)
- Build config: icon, splash, `app.json` (1.0.0 / build 1 / versionCode 1, export-compliance,
  Android manifest diet + LAN-scoped cleartext), `eas.json` (iOS + Android profiles).
- Demo Mode + privacy policy (`landing/privacy.html`).
- Listing copy — English (`store/listing.md`) + 8 localized (`store/listing-localized.md`) +
  the Play-specific fields (`store/play-listing.md`: short descriptions, Data safety draft,
  content-rating draft).
- Screenshots — 6.9" English (`store/screenshots/`) + localized 6.5" (`store/screenshots-6.5/`);
  Play-legal 2:1 conversions generated into `fastlane/metadata/android/*/images/`.
- App Preview poster (`store/app-preview-poster.png`) + Play feature graphic
  (`fastlane/metadata/android/en-US/images/featureGraphic.png`).
- Review notes (`store/review-notes.txt`, plus the Android note in `store/play-listing.md`).
- **fastlane** trees for both stores: deliver (`fastlane/metadata/`, `fastlane/screenshots/`)
  and supply (`fastlane/metadata/android/`), each uploading in one command.

## The App Store submission, start to finish

### 0. 🔑 Deploy the privacy page
Publish the landing site so `https://dreamlayer.app/privacy.html` resolves (Apple and Google
both check it).

### 1. 🔑 Get an App Store Connect API key (once)
App Store Connect → Users and Access → Integrations → App Store Connect API → **+** →
role *App Manager*. Download the `AuthKey_XXXX.p8`, and note the **Key ID** and **Issuer ID**.
Create `phone-app/fastlane/asc_key.json` (gitignored — never commit it):
```json
{ "key_id": "XXXXXXXXXX", "issuer_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "key": "-----BEGIN PRIVATE KEY-----\n...contents of the .p8...\n-----END PRIVATE KEY-----",
  "in_house": false }
```

### 2. 🔑 Register the App ID + create the app record
- Developer portal → Identifiers → App IDs → `com.letsgettoworkbro.dreamlayer` (no capabilities).
- App Store Connect → Apps → **+** → New App (name "DreamLayer", the bundle id, SKU).
- Copy the app's numeric **Apple ID** into `eas.json` → `submit.production.ios.ascAppId`, and your
  **Apple ID email** + **Team ID** into the other two placeholders there.

### 3. 🔑 Build + upload the binary
```bash
cd phone-app
npm i -g eas-cli && eas login          # your Expo account
npm run build:ios                      # EAS cloud build, signs with your Apple cert
npm run submit:ios                     # uploads the .ipa → TestFlight
```
Install from TestFlight and run the pre-flight checklist in `APP_STORE.md` on a device.

### 4. Push the whole listing (metadata + screenshots, all locales) — automated
```bash
cd phone-app
brew install fastlane                  # or: gem install fastlane
fastlane metadata api_key_path:./fastlane/asc_key.json
```
This uploads name/subtitle/keywords/description/promo/release-notes for en-US, es-ES, fr-FR, de-DE,
it, pt-BR, ja, ko, zh-Hans, plus screenshots and the review notes, from the prepared tree.
(Use `fastlane copy` for text-only, `fastlane shots` for screenshots-only.)

### 5. 🔑 Finish in App Store Connect (a few UI-only fields)
- **App Privacy** questionnaire (see `APP_STORE.md` §7 — "Data Not Collected" for the local path;
  disclose the opt-in cloud nuance).
- **Age rating** questionnaire → 4+.
- **Export compliance**: exempt (already set via `ITSAppUsesNonExemptEncryption:false`).
- Attach the TestFlight build to the 1.0.0 version.

### 6. 🔑 Submit
Flip `submit_for_review(true)` in `fastlane/Deliverfile` and re-run `fastlane metadata`, **or** click
**Submit for Review** in App Store Connect. Respond to any reviewer message with `store/review-notes.txt`.

---

## The Google Play submission, start to finish

The same shape as iOS: EAS builds and signs, fastlane pushes the listing, and the handful of
console questionnaires are pre-drafted so they're copy-paste. Step 0 (privacy page) is shared.

### P1. 🔑 Create the Play Console app record
- [Play Console](https://play.google.com/console) → **Create app** → name "DreamLayer",
  default language English (US), App (not game), Free.
- App content → **Privacy policy** → `https://dreamlayer.app/privacy.html`.

### P2. 🔑 Service account key (once) — the Android `asc_key.json`
Play Console → Setup → API access → create/link a Google Cloud project → create a
**service account** with the *Release manager* role, download its JSON key, and save it as
`phone-app/fastlane/play_key.json` (**gitignored — never commit**). `eas.json`
(`submit.production.android`) and the fastlane `play_metadata` lane both read that path.

### P3. 🔑 Build the AAB + first upload
```bash
cd phone-app
npm i -g eas-cli && eas login          # your Expo account
npm run build:android                  # EAS cloud build — EAS creates & stores the
                                       # upload keystore on first run (say yes)
```
Google requires the **first** AAB to be uploaded by hand: Play Console → Testing →
**Internal testing** → Create release → upload the `.aab` from the EAS build page → save.
(Opt into **Play App Signing** when asked — EAS's keystore is the upload key.)
Every build after that is one command: `npm run submit:android` (goes to the internal
track as a draft release; promote in the console when ready).

### P4. Push the whole Play listing (text + graphics, all 9 locales) — automated
```bash
cd phone-app
fastlane android play_metadata         # regenerates fastlane/metadata/android/ from
                                       # store/listing*.md + store/play-listing.md, then
                                       # uploads titles, descriptions, changelogs, the
                                       # feature graphic and 2:1 screenshots. No binary.
```

### P5. 🔑 The console questionnaires (copy-paste from the drafts)
All pre-drafted in `store/play-listing.md`:
- **Data safety** → "no data collected / no data shared", with the opt-in-cloud nuance
  pasted into the notes — sourced from `landing/privacy.html`, say so.
- **Content rating** → Utility, no to everything → Everyone / PEGI 3.
- **Target audience** → 13+, not "Designed for Families".
- Ads declaration → **No ads**.

### P6. 🔑 Roll out
Internal testing → promote the release to **Production** (or straight to a closed track for
friends first). Respond to any reviewer message with `store/review-notes.txt` + the Android
note from `store/play-listing.md`.

---

### Ship listing updates on push (GitHub Actions)
`.github/workflows/appstore-metadata.yml` runs `fastlane deliver` (metadata + screenshots only —
never a binary, never submit-for-review) on manual dispatch, and on pushes to `main` that touch
`store/listing*.md`, `store/review-notes.txt`, or `fastlane/screenshots/**`. It regenerates the
metadata tree from the listing sources first (`scripts/build-appstore-metadata.mjs`), so editing the
copy is enough. Add three repo secrets and it's hands-off:
`ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8` (paste the whole `.p8`). Without them the job safely
no-ops. Edit `store/listing.md` → push → the listing updates itself.

### Why not fully headless here?
`eas build`/`eas submit` and `fastlane` all authenticate as **you** (Apple ID 2FA, your ASC API
key, or your Play service account) and produce binaries signed with **your** certificates and
keystores. Those secrets and the paid memberships are yours; this environment has neither, and
publishing is an outward action you should drive. The automation above is the closest to "one
command" that's safe — your hands-on part is the 🔑 steps.
