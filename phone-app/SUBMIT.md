# DreamLayer — one-command-ish submission (what's automated vs. what only you can do)

Everything that *can* be prepared is prepared. The steps below that need **your Apple account**
are marked 🔑 — they authenticate as you and/or build a signed binary, which cannot be done from a
shared/CI Linux box on your behalf. Run them from your Mac.

## What's already done (in the repo)
- Build config: icon, splash, `app.json` (1.0.0 / build 1 / export-compliance), `eas.json`.
- Demo Mode + privacy policy (`landing/privacy.html`).
- Listing copy — English (`store/listing.md`) + 8 localized (`store/listing-localized.md`).
- Screenshots — 6.9" English (`store/screenshots/`) + localized 6.5" (`store/screenshots-6.5/`).
- App Preview poster (`store/app-preview-poster.png`).
- Review notes (`store/review-notes.txt`).
- **fastlane** metadata + screenshots tree (`fastlane/metadata/`, `fastlane/screenshots/`) so the
  whole listing uploads in one command.

## The submission, start to finish

### 0. 🔑 Deploy the privacy page
Publish the landing site so `https://dreamlayer.app/privacy.html` resolves (Apple checks it).

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

### Ship listing updates on push (GitHub Actions)
`.github/workflows/appstore-metadata.yml` runs `fastlane deliver` (metadata + screenshots only —
never a binary, never submit-for-review) on manual dispatch, and on pushes to `main` that touch
`store/listing*.md`, `store/review-notes.txt`, or `fastlane/screenshots/**`. It regenerates the
metadata tree from the listing sources first (`scripts/build-appstore-metadata.mjs`), so editing the
copy is enough. Add three repo secrets and it's hands-off:
`ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8` (paste the whole `.p8`). Without them the job safely
no-ops. Edit `store/listing.md` → push → the listing updates itself.

### Why not fully headless here?
`eas build`/`eas submit` and `fastlane` all authenticate as **you** (Apple ID 2FA or your ASC API
key) and produce a binary signed with **your** Developer certificate. Those secrets and the paid
membership are yours; this environment has neither, and publishing is an outward action you should
drive. The automation above is the closest to "one command" that's safe — your hands-on part is the
🔑 steps.
