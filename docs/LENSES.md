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
- **Waypath Lens** — "where is it / where do I go": your keys are 12m to your
  left, the exit is behind you — direction + distance from your own anchors.

## 👤 People — *who's around you*

Only people you know; never strangers.

- **Social Lens** — recognises your own contacts and labels them.
- **Timbre** — familiar voices glow as waveforms at the rim; strangers are
  anonymous static.
- **Name Capture** — someone introduces themselves out loud → the name is
  kept automatically, and their dossier starts.

## ⚖️ Truth — *what's true, and where beliefs come from*

One family, three directions.

- **Truth Lens** — outward: another person's credibility (explicit, never
  passive).
- **Candor** — inward: your own story kept consistent.
- **Provenance Lens** — backward: trace a belief to its origin and standing
  (who told you, when, corroborated or contested).

## 🌍 World — *understand what you look at*

- **Oracle** — look at anything → know it: recognise the object and show a
  contextual panel (objects, not people). The flagship of World.
- **Label Lens** — your own facts about a product/food/menu: dietary rules
  you set ("you're avoiding dairy"), whether you own or returned it,
  allergens. Privacy-safe half of "superhuman shopping"; the prices/reviews
  half rides the opt-in cloud tier.
- **AI Brain** — name and explain anything; ask your own files/mail. Tiered:
  on-device → your Mac mini → opt-in cloud.
- **Rosetta Lens** — translate text you *look at* (a menu, a sign): the eye.
- **Puente** — live voice translation: the ear. Together, Rosetta + Puente
  are "understand any language."
- **Scholar** — look at a test question and the answer is on the glass; look at
  a form and each field says what to write; look at dense legal or technical
  text and it comes back in plain words. Reads through the Brain's vision tier
  (local first, cloud only when opted in), veil-gated.

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
- **Glance Arbiter** *(the router)* — no mode picker: on a look it decides
  which lens applies (answer / fill / translate / identify / name), firing the
  clear winner or offering a one-tap chooser when ambiguous. It learns which
  lens you prefer per kind of scene. See
  [Attention and focus](gitbook/attention-focus.md).
- **Atmosphere** *(ambient light and feel)* — **Inner Weather** (your body
  churns the core, the room storms the rim), the **Prism Lens** (a reactive
  kaleidoscope), and **Palette Cycling** (zero-cost motion by recolouring,
  not redrawing).

---

The grouping is data, not prose: `from dreamlayer.lenses import LENSES,
lens_of`. Nothing about the six-lens model changes how any feature runs — it's
purely how we *tell the story*.
