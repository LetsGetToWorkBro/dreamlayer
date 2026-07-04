# DreamLayer — landing page

A single-file, scroll-driven marketing page for DreamLayer, built in the same
design system as the product (see [`phone-app/DESIGN.md`](../phone-app/DESIGN.md)):
the halo palette, the `cubic-bezier(0.16, 1, 0.3, 1)` "arrive" curve, the
2400 ms breath, and entrance motion mirrored from `phone-app/src/ui/`.

The hero background is a JavaScript port of `DreamCanvas.tsx` — the same
value-noise lattice, two-band weather, and Line Field 2.0 the glasses run.

## Serve

No build step. Any static host:

```bash
cd landing && python3 -m http.server 8080    # open http://localhost:8080
```

## Assets

Everything in `assets/` is derived from this repo:

| Asset | Source |
|---|---|
| `hud/*.png` | verbatim copies of `assets/hud/samples/` — Meridian Solid renderer output, 256 px, one eye (used in the marquee and the Privacy Veil backdrop) |
| `software/phone_*.png` | downscaled copies of `docs/gitbook/assets/phone/` — real iOS-app screenshots |
| `software/mac_panel.png` | a cropped, downscaled slice of `docs/gitbook/assets/panel/panel_full.png` — the Mac Brain control panel |

The three "See it move" orbs are **not** videos — they're live `<canvas>`
animations drawn in JS (`data-hud="horizon|recall|saved"`), reusing the app's
own motion (the value-noise field, the focus condense/recede law, a spring
check). This avoids the iOS Low-Power-Mode autoplay block that stops `<video>`.

Fonts load from Google Fonts (Space Grotesk) with a system-stack fallback;
the page works fully offline minus that one request. All motion respects
`prefers-reduced-motion`.
