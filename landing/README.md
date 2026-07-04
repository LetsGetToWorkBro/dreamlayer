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
| `horizon.mp4` | `scripts/export_meridian_motion.py` `wake_and_aurora` — the device Lua stepped on a 50 ms clock |
| `focus.mp4` | same exporter, `focus_physics` (ObjectRecall v3 spatial card; settled hold extended for the loop) |
| `saved.mp4` | same exporter, `save_moment` (SavedMemory v2 jewel; hold + crossfade back to idle) |
| `hud/*.png` | verbatim copies of `assets/hud/samples/` — Meridian Solid renderer output, 256 px, one eye |

To regenerate the clips after a renderer change:

```bash
pip install -e ./host-python lupa pillow
python3 scripts/export_meridian_motion.py        # writes out/meridian_motion/
# upscale + encode (see git history of this file for the exact ffmpeg calls)
```

Fonts load from Google Fonts (Space Grotesk) with a system-stack fallback;
the page works fully offline minus that one request. All motion respects
`prefers-reduced-motion`.
