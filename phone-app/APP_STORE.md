# DreamLayer iOS — App Store submission runbook

A step-by-step to ship the DreamLayer phone app and pass App Review on the **first** try.
The code/asset prep in the repo is done; this file is the operational checklist for the parts
that need your Apple account. Work top to bottom.

- **Bundle ID:** `com.letsgettoworkbro.dreamlayer`
- **App name:** DreamLayer · **Version:** 1.0.0 · **Build:** 1
- **Category (suggested):** Productivity · **Age rating:** 4+
- **Not applicable:** no login/account, no in-app purchase, no push server, no tracking/ads.

> Why we expect a first-pass approval: the two things that reject hardware-companion apps are
> handled in code — **Demo Mode** (Guideline 4.2) and a **hosted privacy policy** (5.1.1) — and the
> product ships with an explicit honesty contract (see `docs/gitbook/hardware-seams.md`) that
> defuses the "misleading unreleased hardware" guideline (2.3.x).

---

## 0. Prerequisites (one time)
1. **Apple Developer Program** membership (paid, $99/yr) on the account that will own the app.
2. Install tooling: `npm i -g eas-cli` and sign in with `eas login` (Expo account).
3. From `phone-app/`, confirm the config resolves: `npx expo-doctor` and
   `npx expo config --type public` (should show icon, splash, `ios.buildNumber`, bundle id,
   `ITSAppUsesNonExemptEncryption: false`).

## 1. Fill in `eas.json` submit credentials
Edit `phone-app/eas.json` → `submit.production.ios` and replace the three placeholders:
- `appleId` — your Apple ID email.
- `appleTeamId` — Apple Developer **Team ID** (Apple Developer → Membership).
- `ascAppId` — the App Store Connect **App ID** (a numeric id you get in step 3, after the app
  record exists). You can build before you have this; you only need it for `eas submit`.

## 2. Register the App ID (identifier)
Apple Developer → **Certificates, Identifiers & Profiles → Identifiers → +** → App IDs → App.
- Description: `DreamLayer`. Bundle ID (explicit): `com.letsgettoworkbro.dreamlayer`.
- **Capabilities: leave all off.** The app needs none (no push, no sign-in, no IAP).
- EAS will create/manage the signing certificate and provisioning profile for you during the build.

## 3. Create the app record in App Store Connect
[App Store Connect](https://appstoreconnect.apple.com) → **Apps → + → New App**.
- Platform: iOS · Name: **DreamLayer** · Primary language: English (U.S.)
- Bundle ID: pick `com.letsgettoworkbro.dreamlayer` · SKU: `dreamlayer-ios-001`
- After it's created, copy the **Apple ID** (numeric) from the App Information page into
  `eas.json` `ascAppId`.

## 4. Build and upload to TestFlight
From `phone-app/`:
```
npm run build:ios          # eas build -p ios --profile production
npm run submit:ios         # eas submit -p ios --profile production  (uploads the .ipa)
```
- On first build, EAS prompts to create the Distribution certificate + provisioning profile — say yes.
- After processing, the build appears under **TestFlight**. Install it on a device via the
  TestFlight app and run the **pre-flight checklist** (section 9) on real hardware. This device pass
  is the real gate — do it before submitting for review.

> **Ready-made:** the full listing copy (name, subtitle, keywords, description, What's New,
> URLs, category) is in **`store/listing.md`**; localized copy for 8 markets (ES/FR/DE/IT/pt-BR/
> JA/KO/zh-Hans) in **`store/listing-localized.md`**; the six upload-ready screenshots in
> **`store/screenshots/`** (1290×2796); and an App Preview poster / hero title card at
> **`store/app-preview-poster.png`** (1290×2796). Sections 5–6 below summarize them.

## 5. Store listing (App Store tab → the 1.0.0 version)
- **Subtitle (30 char):** e.g. `Your memory, on your glasses`
- **Promotional text:** one honest line — companion app for Brilliant Labs Halo + an optional
  self-hosted Mac Brain; try it with sample data, no hardware needed.
- **Description:** describe what it does, and **state plainly** that full features require the Halo
  glasses (pre-release) and/or a Mac "Brain", and that **"Explore with sample data"** lets you try
  the whole app without hardware. Do not claim the glasses ship today.
- **Keywords:** `memory, notes, reminders, assistant, AR, glasses, privacy, companion`
- **Support URL:** `https://dreamlayer.app` · **Marketing URL:** `https://dreamlayer.app`
- **Privacy Policy URL:** `https://dreamlayer.app/privacy.html`  ← must be live before submit
  (deploy the landing site so this resolves).

## 6. Screenshots (iPhone only — `supportsTablet:false`)
Provide the **6.9"/6.7"** iPhone set (App Store accepts the 6.9" set for all modern iPhones).
Capture from **Demo Mode** so screens are populated:
- Turn on Demo Mode (onboarding → "Explore with sample data", or Settings → Demo Mode).
- Screens worth shipping: **Now** (brief + promise), **Memories**, **People** (debts),
  **Messages**, **Brain** (or **Saga**).
- Capture on an iPhone 15/16 Pro Max simulator or device (Cmd-S in Simulator). The
  "Sample data · Demo Mode" banner is fine to show — it reads as honest.

## 7. App Privacy ("nutrition labels")  → App Store Connect → App Privacy
Answer truthfully; the iOS app itself collects almost nothing:
- **Data collection:** the app does **not** collect data in the default/local path. Choose
  **"Data Not Collected"** unless you add analytics later.
- **Tracking:** No. There is no IDFA / ad SDK / third-party tracker in the app.
- **Camera:** used only on-device to scan a pairing QR; nothing is stored or sent → not "collected".
- **The opt-in cloud nuance:** if you want to be maximally conservative, disclose that when the user
  enables cloud AI, the **content of that request** is sent to their chosen provider (OpenAI /
  Anthropic / Google / OpenRouter) to produce a result. This is user-initiated and covered by the
  privacy policy; it is processing by a third party the user selects, not data you collect.
- Keep this consistent with `https://dreamlayer.app/privacy.html`.

## 8. Age rating
Answer the questionnaire — no objectionable content → **4+**.

## 9. Pre-flight checklist (run on the TestFlight build before submitting)
- [ ] App launches; first run shows the onboarding tour (no crash, no blank).
- [ ] "Explore with sample data" turns on Demo Mode and lands on **Now**, populated.
- [ ] Every tab is alive in Demo Mode — **no "Connect your Mac mini" dead-ends**:
      Now, Memories, People, Messages, Brain, Settings (+ Labs: Saga, Rewind, Profile, Brief).
- [ ] The "Sample data · Demo Mode" banner shows on demo screens.
- [ ] Camera permission prompt copy is correct (QR pairing) and only appears when scanning.
- [ ] Settings → Privacy & legal → **Privacy policy** opens `dreamlayer.app/privacy.html`.
- [ ] Settings → Danger zone → Erase all memories works (data deletion path).
- [ ] App icon + splash render correctly (no default Expo icon).
- [ ] No obvious placeholder/mock screens are reachable (Confluence/Rehearsal are hidden).

## 10. App Review Information (the linchpin — fill the "Notes" box)
Paste notes like:
```
DreamLayer is a companion app for Brilliant Labs Halo smart glasses (pre-release) and an
optional self-hosted "Brain" that runs on the user's own Mac. There is NO login or account.

To review the full app without any hardware, please use Demo Mode:
  • On the first screen tap "Begin", advance to the last step, and tap
    "Explore with sample data"  — OR  Settings → Try it → Demo Mode.
This populates every screen with clearly-labeled sample data (a "Sample data · Demo Mode"
banner is shown), so you can navigate the entire app.

Notes:
  • No demo account is needed (the app has no login).
  • The camera is used only to scan a pairing QR from the Mac Brain.
  • Data is stored on-device; users can erase everything in Settings → Danger zone.
  • Cloud AI is opt-in and off by default; privacy policy: https://dreamlayer.app/privacy.html
```
- Sign-in required: **No**. Contact info: your name/email/phone.

## 11. Export compliance
When prompted: the app uses only standard encryption (HTTPS) and is **exempt**. This matches
`ITSAppUsesNonExemptEncryption: false` already set in `app.json`, so you shouldn't be asked again.

## 12. Submit & respond
- Attach the TestFlight build to the 1.0.0 version → **Add for Review** → **Submit**.
- If a reviewer replies in Resolution Center, answer using the section-10 notes (point them at
  Demo Mode). Do not argue guidelines; show them how to exercise the app.

---

## Rejection-risk map (guideline → how it's mitigated)
| Guideline | Risk | Mitigation (where) |
|---|---|---|
| 2.1 / 4.2 Minimum functionality | Inert without pre-release hardware | **Demo Mode** populates every screen; review notes point to it (`src/demo/`, onboarding, Settings) |
| 5.1.1 Privacy — policy | No policy existed | Hosted `dreamlayer.app/privacy.html` + in-app link (Settings → Privacy & legal) |
| 5.1.1 Privacy — data & labels | Cloud path sends content to LLMs | Disclosed in policy + App Privacy answers (section 7) |
| 5.1.1(v) Account deletion | — | No account exists; local "Erase all memories" documented in notes |
| 2.3.1 Accurate metadata | "Phone is the brain" overpromise | Copy softened to honest companion/hub framing (`app/brain.tsx`) |
| 2.3.x Misleading hardware | Glasses not shipping | Honest "requires Halo / pre-release" framing; `docs/gitbook/hardware-seams.md` |
| 4.0 Design | Missing icon/splash | Full-bleed opaque icon + splash added (`assets/`, `app.json`) |
| 5.1.1 Export compliance | Prompt at upload | `ITSAppUsesNonExemptEncryption: false` |
| 2.5.2 Executable code | Plugins install to the Mac Brain, not iOS | No code is downloaded/run on iOS; plugin execution is on the user's Mac |

## If you later add accounts, IAP, or analytics
Each changes the review surface: accounts → add Sign in with Apple + account **deletion**
(5.1.1(v)); IAP → StoreKit + the paid-tier must be real; analytics → update App Privacy labels
and the policy. The current build has none of these on purpose.
