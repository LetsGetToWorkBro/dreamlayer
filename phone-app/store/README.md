# App Store assets

Everything needed for the App Store Connect listing. See `../APP_STORE.md` for the full
submission runbook.

## Contents
- **`listing.md`** — English master listing (name, subtitle, keywords, description, What's New, URLs).
- **`listing-localized.md`** — full localized listings for 8 markets
  (ES · FR · DE · IT · pt-BR · JA · KO · zh-Hans).
- **`review-notes.txt`** — copy-paste block for App Store Connect → App Review Information → Notes.
- **`screenshots/`** — primary set, **1290×2796** (iPhone 6.9"/6.7"), English. Upload order 01–06.
- **`screenshots-6.5/<lang>/`** — fallback set, **1242×2688** (iPhone 6.5"), localized captions.
- **`app-preview-poster.png`** — **1290×2796** hero / App Preview poster frame.

## Localized screenshots
`screenshots-6.5/` contains caption-localized sets for **en, es, fr, de, it, pt-BR, ja**. The app
UI itself is English (the app isn't internationalized yet); only the marketing captions are
translated, which is standard and matches the app's actual on-screen language.

**Korean (ko) and Chinese Simplified (zh-Hans)** captions are written in `listing-localized.md`
but their screenshots were not rendered here because the build environment lacks a Hangul / CJK
font. Options: (a) let those stores fall back to the default (English) screenshot set — allowed by
App Store Connect; or (b) re-run `gen-shots.mjs` on a machine with Noto Sans KR / Noto Sans SC
installed, adding `ko`/`zh-Hans` entries to the caption map.

## Regenerating
The screenshots are composited from the real app UI captured in Demo Mode:
1. Serve the web export and capture app screens (`shot-hires.mjs`, banner hidden via `#dl-demo-banner`).
2. Composite with captions on the cinematic backdrop (`gen-store.mjs` for 6.9", `gen-shots.mjs`
   for 6.5", `gen-poster.mjs` for the poster).
Re-run after UI changes so the store art stays truthful to the app.

## Upload sizes (App Store Connect)
- iPhone 6.9" display: 1290×2796 (this set is accepted here; 1320×2868 also allowed).
- iPhone 6.5" display: 1242×2688 (the fallback set).
Uploading the 6.9" set alone satisfies the requirement; the 6.5" set is a polish/fallback.
