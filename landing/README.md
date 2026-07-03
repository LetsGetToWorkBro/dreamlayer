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
| `weather.mp4` | frame-by-frame render of the `DreamCanvas.tsx` mock-tick math (Dream Mode ambient weather) |
| `recall.mp4` | the Focus law (`motion.ts` `signatures.focus`) applied to the object-recall card |
| `reel.mp4` | actual frames from `out/mindblow_demo/` (the flagship demo scenario), crossfaded |
| `hud/*.png` | verbatim copies of `assets/hud/samples/` — real renderer output, 256 px, one eye |

Fonts load from Google Fonts (Space Grotesk) with a system-stack fallback;
the page works fully offline minus that one request. All motion respects
`prefers-reduced-motion`.
