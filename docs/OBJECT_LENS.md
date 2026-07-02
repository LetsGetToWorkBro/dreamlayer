# Object Lens — look at a thing, get a contextual panel

`host-python/src/dreamlayer/object_lens/`

The "invisible UI for objects": turn toward something and a small panel
appears — what it is, what *you* already know about it, and what you can do
with it. A laptop shows recent files; a car shows tire pressure; a book you
own says "you already own this"; a mug says "return this to Sam."

It's world-facing on **objects only**. If the recogniser names a person the
lens declines — people are Social Lens's consented domain, and that boundary
is enforced in the recogniser (`PERSON_LABELS`).

## The two hard parts, honestly handled

**1. General object recognition.** Naming arbitrary objects (not just faces)
needs a vision model on the Halo NPU. The recogniser is a clean seam:

```python
ObjectRecognizer(classify_fn=my_quantized_npu_model)   # real
ObjectRecognizer()                                     # deterministic mock
```

`classify_fn(frame) -> (label, confidence, attributes)`. With no model, a
deterministic mock maps frame statistics onto a small taxonomy, so every
other part — providers, panels, HUD, tests — runs today without a model.

**2. Deep external integrations.** "Recent files from your laptop", "tire
pressure from the car" need real integrations. Those are **providers fed by
an injected `data_source` callable** — that's the whole seam:

```python
lens.registry.register(LaptopProvider(my_laptop_agent))   # returns recent files
lens.registry.register(CarProvider(my_obd_reader))        # returns tire pressure
lens.registry.register(PlantProvider(my_soil_sensor))
```

Wire the callable to a real source and the panel fills in; the demo passes
fixed data. Nothing about the framework pretends the integration exists — it
just leaves a typed hole for it.

## Providers

A panel is *assembled*, not hard-coded. Each `PanelProvider` decides whether
it applies to a sighting and contributes rows; the registry merges them.

- **MemoryProvider** (on-device, ships by default) — your own memory of this
  object: prior sightings, where you last saw it, whether you own one. Your
  data only; private sightings (`meta.private`) never surface.
- **NoteProvider** — reminders/notes you anchored to a kind of object.
- **LaptopProvider / CarProvider / PlantProvider** — the integration seams
  above.

## Privacy

Veiled means blind (`allow_capture` gate), a person is never panelled, and
the built-in providers read only your own on-device memory. External data
appears only through providers you explicitly register. Orchestrator:
`look_at_object(frame)`.

## Try it

```
python scripts/run_demo_object_lens.py
```

Looks at a laptop, a book you own, a mug with a note, a car, and a plant —
printing each contextual panel — then declines a person.

## Tests

`test_object_lens.py` — recognition (determinism, blank-frame and
low-confidence drops, the person boundary, pluggable classifier +
attributes), each provider (memory recall + ownership + the private guard,
notes, the three integration seams incl. a broken source), registry merge,
and the lens end to end (panel build, veil gate, person → no panel,
orchestrator wiring).
