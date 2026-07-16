# DreamLayer — Google Play listing

The Play half of the store kit. The *copy* is the same product voice as the App
Store listing — full descriptions and release notes are reused verbatim from
`listing.md` / `listing-localized.md` (one source of truth); this file adds only
what Play needs that Apple doesn't: the ≤80-char short description per locale,
the feature graphic, the Data safety draft, and the content-rating draft.

`node scripts/build-play-metadata.mjs` regenerates the fastlane **supply** tree
(`fastlane/metadata/android/<locale>/`) from these sources and hard-fails if any
short description exceeds 80 characters. `python3 scripts/make-play-assets.py`
renders the feature graphic and converts the iOS screenshots to Play-legal
geometry (Play caps phone screenshots at 2:1 — the iPhone 6.9"/6.5" frames are
2.17:1, so each is pillarboxed onto a 1080×2160 canvas).

---

## App name (max 30)
```
DreamLayer
```

## Short description (max 80, per locale)

| Play locale | Short description |
|---|---|
| en-US | Your memory, on your glasses — a private memory layer for the real world. |
| es-ES | Tu memoria, en tus gafas: una capa de memoria privada para el mundo real. |
| fr-FR | Ta mémoire, sur tes lunettes — une mémoire privée pour le monde réel. |
| de-DE | Gedächtnis für deine Brille – privat, lokal, für die echte Welt. |
| it-IT | La tua memoria, sugli occhiali: privata, locale, per il mondo reale. |
| pt-BR | Sua memória, nos seus óculos — privada, local, para o mundo real. |
| ja-JP | メガネにあなたの記憶を——現実世界のためのプライベートな記憶レイヤー。 |
| ko-KR | 당신의 기억을, 안경에 — 현실 세계를 위한 프라이빗 기억 레이어. |
| zh-CN | 你的记忆，戴在眼镜上——为真实世界打造的私密记忆层。 |

## Full description (max 4000, per locale)
Reused verbatim from the App Store `## Description` blocks — `listing.md`
(English) and `listing-localized.md` (8 locales). Play locale mapping:
`it → it-IT`, `ja → ja-JP`, `ko → ko-KR`, `zh-Hans → zh-CN`; the rest match.

## Release notes (v1 / versionCode 1)
Reused from the `What's New` lines in the same files.

## Graphics
- **App icon (512×512):** exported from `assets/icon.png` (Play Console
  re-uploads it; the binary's adaptive icon is separate).
- **Feature graphic (1024×500, required):**
  `fastlane/metadata/android/en-US/images/featureGraphic.png` — the little Mac
  on the brand starfield with the Chicago wordmark; regenerate with
  `python3 scripts/make-play-assets.py`.
- **Phone screenshots:** `fastlane/metadata/android/<locale>/images/
  phoneScreenshots/` — the six App Store shots per locale, pillarboxed to
  1080×2160 (Play's 2:1 limit). Locales without a localized set (ko-KR, zh-CN)
  ship the en-US shots, same as the App Store setup.

## Category & contact
- **Application type:** App · **Category:** Productivity
- **Email:** info@labyrinth.vision · **Website:** https://dreamlayer.app
- **Privacy policy URL:** https://dreamlayer.app/privacy.html (must be live)

---

## Data safety form — draft answers

Source of truth: `landing/privacy.html` (say so in the review notes). The
honest posture is strong and simple:

| Question | Answer |
|---|---|
| Does your app collect or share any of the required user data types? | **No** |
| Is all of the user data collected by your app encrypted in transit? | (not asked when nothing is collected) |
| Do you provide a way for users to request that their data is deleted? | (not asked when nothing is collected; the in-app "Erase all memories" exists regardless) |

Why "No" is the honest answer, pre-written for the reviewer:

- The app has **no account, no analytics, no ads, no tracking SDKs** — nothing
  is transmitted to the developer at all (privacy.html §4: "we do not receive
  your memories, messages, or media").
- Memories, messages, settings live **on-device**; a paired Brain is the
  **user's own computer** on the **user's own network**. Phone↔Brain traffic
  never touches DreamLayer servers (§2).
- Camera frames are processed **on-device only** to read the pairing QR —
  never stored, never uploaded (§1).
- The one nuance: **opt-in cloud AI** (§3). Off by default. When the user
  turns it on and supplies their own key, the text of that request goes
  **directly from the user's device to the provider the user chose** (OpenAI,
  Anthropic, Google, OpenRouter, or their own Ollama). This is a
  user-initiated transfer to a service the user configured — it is not
  collection or sharing by DreamLayer, and no DreamLayer server is in the
  path. Disclose it in the form's free-text notes exactly like this, the same
  way the App Store privacy answer discloses it (APP_STORE.md §7).

🔑 The final tick-boxes are owner attestations in Play Console — copy the
table above, paste the nuance paragraph into "Other app functionality" notes.

## Content rating questionnaire — draft answers

- Category: **Utility / Productivity**.
- Violence, sexuality, profanity, drugs, gambling (simulated or real): **No**
  to all.
- User-generated content visible to others: **No** (nothing is public; the
  optional Confluence bond shares state only between two consenting paired
  users' own devices).
- Does the app share the user's current location with third parties: **No**.
  The app never requests a location permission (none is in the manifest).
  Waypath routes between coordinates the user *types*, fetched over HTTPS
  from an OSRM endpoint only when the user explicitly asks for a route — the
  self-hostable public demo server by default, swappable for your own
  (`src/nav/osrm.ts`). No advertising use, no background anything.
- Expected rating: **Everyone / PEGI 3**.

## Target audience
**13+** (do not opt into "Designed for Families"; the app is not directed at
children — privacy.html §6).

## Play review notes
Reuse `store/review-notes.txt` verbatim (Demo Mode steps apply unchanged on
Android), plus one Android-specific line:

> Android note: the app requests only CAMERA (QR pairing) and, on Android 13+,
> POST_NOTIFICATIONS at first relevant use (morning brief / message mirror).
> Cleartext HTTP is scoped to the user's own LAN (network security config +
> in-app private-range enforcement); see the privacy policy for the
> architecture.
