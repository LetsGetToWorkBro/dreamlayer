# DreamLayer — Design System

One surface, one rhythm, one motion. This is the contract every screen in the
phone app (and the Mac Brain panel) follows so the product reads as a single,
calm, tactile thing. When you add a screen, compose it from the primitives
here — don't reinvent spacing, color, or motion locally.

> **North star:** the interface should feel like the glasses' HUD in your hand —
> dark, luminous, unhurried. Nothing jumps; everything *arrives*. Every touch
> answers back.

---

## 1. Color

Source of truth: [`src/ui/theme/colors.ts`](src/ui/theme/colors.ts).

The app palette (`colors`) is the phone's own surface; `haloPalette` is the
exact mirror of the glasses (`halo-lua/display/palette.lua`) used only where the
phone previews the HUD — keep them separate on purpose.

| Token | Value | Use |
|---|---|---|
| `background` | `#000000` | the void behind everything |
| `surface` | `#0E1416` | cards, the tab bar |
| `surfaceElevated` | `#141F23` | raised surfaces, inputs |
| `textPrimary` | `#FFFFFF` | titles, answers |
| `textSecondary` | `#8A9BA3` | captions, supporting copy |
| `accentMemory` | `#2FD4C4` | the brand teal — primary actions, "on" |
| `accentAttention` | `#FF6B5E` | promises, incognito, "look here" |
| `accentSuccess` | `#56D364` | confirmations, live |
| `accentError` | `#FF5C5C` | destructive, unsigned |
| `borderSubtle` | `#1F2A2E` | 1px hairlines on every card |
| `statusPaused` | `#6B7A82` | muted / disabled |

**Rules**
- One accent per surface. `accentMemory` is the default; reach for another only
  when it *means* something (attention = a promise; error = destroys data).
- Text is only ever `textPrimary` or `textSecondary`. Don't invent greys.
- "On" states take the accent as a border edge (`Card active`), never a fill —
  fills are reserved for primary buttons.

---

## 2. Rhythm — spacing & radius

Source of truth: [`src/ui/theme/spacing.ts`](src/ui/theme/spacing.ts).

An **8-point grid** with a 4 half-step. Every margin, gap, and pad is a token —
never a raw number.

```
xs 4 · sm 8 · md 12 · lg 16 · xl 20 · xxl 24 · xxxl 32 · huge 48
```

- **`gutter` (24)** is the single horizontal inset every screen shares. It lives
  in `Screen`; don't add your own horizontal padding on top of it.
- **Radius:** `sm 10` (inputs, tags) · `lg 18` (cards) · `pill 999` (buttons,
  chips). Cards and buttons never share a radius — that's how the eye tells a
  surface from an action.

---

## 3. Typography

Source of truth: [`src/ui/theme/typography.ts`](src/ui/theme/typography.ts).

| Style | Size / weight | Use |
|---|---|---|
| `display` | 36 / 700 | screen titles (`ScreenHeader`) |
| `headline` | 26 / 700 | hero answers, big moments |
| `title` | 20 / 600 | card headings, glyphs |
| `body` | 16 / 400 | the reading line |
| `caption` | 13 / 400 | meta, hints, timestamps |
| `eyebrow` | 11 / 600, tracked, UPPER | section labels above a title/card |
| `mono` | 13, monospace | codes, tiers, technical strings |

One title per screen (`display`). Sections are announced by an `eyebrow`, never
a second big title.

---

## 4. Motion

Source of truth: [`src/ui/anim.ts`](src/ui/anim.ts) (timings from
[`src/ui/theme/motion.ts`](src/ui/theme/motion.ts)).

Two verbs, both **native-driven** (`useNativeDriver: true`) and **reduce-motion
aware** (they snap to the end state when `motion.reduceMotion`).

- **`useEntrance(delay?, rise?)`** — a fade + gentle rise (14px) as a view
  mounts. `ScreenHeader`, `Card`, and `EmptyState` use it. Stagger a column by
  passing an increasing `delay` (≈45–60ms per item) — see `memories.tsx`.
- **`usePressScale(to?)`** — a spring scale-down (default `0.96`) while pressed.
  Baked into `Tappable`, so every touch target answers back the same way.

**The easing curve is `cubic-bezier(0.16, 1, 0.3, 1)`** everywhere — a soft,
decelerating "arrive." Don't hand-roll other curves.

**Rules**
- Content *arrives*; it never pops. Anything appearing on mount uses
  `useEntrance` (directly, or via `Card`/`ScreenHeader`).
- Every tappable thing is a `Tappable` (or a component built on it —
  `PrimaryButton`, `PillButton`). No bare `TouchableOpacity` in screens.
- Keep durations in `motion` (`fast 180 · base 240 · slow 400`). If a value
  changes on the HUD, change it here too — the phone breathes with the glasses.

---

## 5. Primitives

All in [`src/ui/components/`](src/ui/components/). Compose screens from these.

| Component | What it is |
|---|---|
| **`Screen`** | The frame: full-bleed background, safe area, one gutter, scroll or fixed body. Start every screen with it. |
| **`ScreenHeader`** | The `display` title block — optional `eyebrow`, `subtitle`, and a right slot (a status pill / action). Rises in on mount. |
| **`Card` / `Section`** | `Card` = the standard surface (one radius, border, pad; `active` accent edge; optional `onPress`; `delay` to stagger). `Section` = the eyebrow label above a group. |
| **`Tappable`** | The one touch primitive — spring scale-on-press. Drop-in for `TouchableOpacity`. |
| **`EmptyState`** | A calm halo ring + line + hint. No screen ever renders a blank void. |
| **`StatusPill`** | Live / paused indicator for a header's right slot. |
| **`HaloMirror`** | A phone-side mirror of the card currently on the glasses. |
| **`Connector` set** | `ConnectorCard`, `SwitchRow`, `Bullet`, `PillButton` — the Brain screen's connect-a-thing vocabulary. |
| **`QrScanner`** | The pairing scanner (lazy-loads `expo-camera`; degrades to "paste instead" where no camera). |
| **`PrimaryButton` / `EyebrowLabel`** | The onboarding CTA and the tracked-caps label. |
| **`OnboardingDots` / `HaloPairingRing`** | Onboarding progress and the pairing ring. |
| **HUD previews** | `CardPreview`, `DreamCanvas`, `HorizonPreview` — SVG mirrors of the glasses' renderer, drawn in `haloPalette` as QA truth. |

### A screen, canonically

```tsx
export default function Example() {
  return (
    <Screen>
      <ScreenHeader title="Example" eyebrow="Section" right={<StatusPill paused={false} />} />
      <Section label="Group" first />
      <Card delay={0}>…</Card>
      <Card delay={45}>…</Card>
    </Screen>
  );
}
```

---

## 6. State & data

- **`useBrainStore`** is the single source of truth for the three brain switches
  (phone-vs-Mac-mini, cloud, incognito), glasses pairing, and capture. UI reads
  it with selectors; it persists to `AsyncStorage` and best-effort syncs to a
  paired Mac mini. `useHaloStore` and `useMemoryStore` are thin facets over it.
- **Local-first & honest:** stores ship with enough seed state that no surface is
  ever empty on first run (`useMemoryStore`), but nothing is fabricated as
  "real" — `purgeAll()` clears it, and live data replaces it when a brain is
  paired.
- **Pairing** ([`src/services/pairing.ts`](src/services/pairing.ts)) is a codec
  verified byte-for-byte against the Python `dreamlayer/pairing.py`. One
  `dreamlayer:` code carries the Brain URL, token, and glasses id.

---

## 7. Principles

1. **Frictionless beats featureful.** One code to pair the trio. One switch per
   idea. The default (phone is the brain, cloud off until you opt in) works
   before any setup.
2. **Nothing pops, everything arrives.** Entrance motion + press feedback are not
   decoration — they're how the app tells you it heard you.
3. **One accent per surface.** Color is meaning, not garnish.
4. **Privacy is visible.** Incognito and capture-pause are one tap and always in
   reach; "off" states read unmistakably muted.
5. **The phone breathes with the glasses.** Timings and the HUD palette are
   mirrored, not re-invented — the two screens are one product.
