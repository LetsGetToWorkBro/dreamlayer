# Prism Lens — the world as a reactive psychedelic overlay

`halo-lua/display/prism.lua` + `host-python/.../dream_mode/prism.py`

A wonder mode. It turns the HUD into a kaleidoscope: a small set of radial
arms, mirrored into `symmetry` sectors, rotating slowly — drawn in the four
dynamic sky slots whose colours are **palette-cycled** through a rainbow ring
(`palette_cycle.lua`). The colour flows through the arms with almost no redraw
cost while the geometry only turns; the two motions together read as
breathing, trailing, impossibly-coloured light.

Honest about the hardware: Halo is a **HUD overlay**, not opaque full
passthrough, so this doesn't repaint your whole visual field — it lays a dense
flowing field *over* your view. That overlay-over-reality quality is exactly
the classic "trails and breathing geometry" phenomenology, so it reads as the
real thing.

## Reactive

The host controller (`PrismLens`) turns ambient sound and motion into the
overlay's intensity and hue speed, so the colours breathe with the room. It
eases the values and re-emits only past a small threshold, so a quiet scene
sends almost nothing. Wire: `{t="prism", active, intensity, symmetry, hue_rate}`
(BLE type `PRISM`, lockstep with `message_types.lua`). In `main.lua` the Prism
Lens takes render precedence while active.

## Safety by construction

This is **aesthetic stylisation, not neurostimulation** — categorically
different from the 40 Hz "Neural Pacer" brainwave-entrainment idea, which was
declined. The palette cycle and rotation are slow and capped, nothing flickers
near photosensitivity thresholds, and `reduce_motion` freezes both the spin
and the palette to a still symmetric bloom — colour without movement.

## Try it

```
python scripts/run_demo_prism.py      # renders out/prism/kaleidoscope.png
```

## Tests

`test_prism.py` — the host controller (enter/exit/react/clamp), the
message-type lockstep, the Lua renderer (inactive draws nothing, active draws
a symmetric field, more symmetry → more arms, colour flows over time,
reduce_motion is static), and driving `{t="prism"}` through the real booted
device loop.
