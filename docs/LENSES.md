# The six lenses of DreamLayer

Twenty-odd features are a hard story. Six lenses are an easy one. This is the
canonical mental model — the same grouping the code carries in
`dreamlayer/lenses.py` (pure metadata; grouping only, no behaviour change).

Every feature keeps its own module, name, and doc. This just says which lens
it lives under, so onboarding, the phone app, and this README all tell one
story.

---

## 🧠 Memory — *your life, remembered*

The resting state and everything about recall.

- **Dream Mode** — ambient sensing; the calm default.
- **Ghost Layer** — memory echoes anchored to the places they happened.
- **Lucid Recall** — ask and receive ("where are my keys?") — now over your
  own files too, via the AI Brain.
- **REM** — the glasses dream the day recombined overnight; the dreaming *is*
  memory consolidation.
- **Yesterlight** — roll your head back and the room replays its own light.
- **Premonition** — your rhythms shimmer just ahead of the now-notch.

## 👤 People — *who's around you*

Only people you know; never strangers.

- **Social Lens** — recognises your own contacts and labels them.
- **Timbre** — familiar voices glow as waveforms at the rim; strangers are
  anonymous static.
- **Name Capture** — someone introduces themselves out loud → keep the name,
  on consent.

## ⚖️ Truth — *what's true, and where beliefs come from*

One family, three directions.

- **Truth Lens** — outward: another person's credibility (explicit, never
  passive).
- **Candor** — inward: your own story kept consistent.
- **Provenance Lens** — backward: trace a belief to its origin and standing
  (who told you, when, corroborated or contested).

## 🌍 World — *understand what you look at*

- **Object Lens** — look at a thing → a contextual panel (objects, not
  people).
- **AI Brain** — name and explain anything; ask your own files/mail. Tiered:
  on-device → your Mac mini → opt-in cloud.
- **Puente** — live voice translation. The *ear*; the Object Lens's read/
  translate is the *eye*.

## 🎯 Life — *do, keep, and build*

- **Commitment Drift** — promises as living HUD objects: bloom, crack,
  shatter by behaviour and time.
- **Saga** — the same commitments as a personal RPG: XP, streaks, rescues.
- **Reality Compiler** — teach a behaviour once and a verified Figment runs
  it forever. Two authoring modes: **Rehearsal** (reactive) and
  **Wayfinding** (linear how-tos).

## 🤝 Together — *two wearers, one sky*

- **Confluence** — bond with another wearer: entangled skies that merge and
  split, silent TinCan pings, weather gifts. Only weather crosses — never
  words, places, or names.

---

## Underneath everything

- **Privacy Veil** *(the spine)* — one gesture and the glasses go fully deaf
  and blind. Nothing seen, heard, or kept. Always available, in every lens.
- **Atmosphere** *(ambient light and feel)* — **Inner Weather** (your body
  churns the core, the room storms the rim), the **Prism Lens** (a reactive
  kaleidoscope), and **Palette Cycling** (zero-cost motion by recolouring,
  not redrawing).

---

The grouping is data, not prose: `from dreamlayer.lenses import LENSES,
lens_of`. Nothing about the six-lens model changes how any feature runs — it's
purely how we *tell the story*.
