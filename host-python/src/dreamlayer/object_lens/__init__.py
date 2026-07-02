"""object_lens — the Object Lens: look at a thing, get a contextual panel.

A world-facing lens for *objects* (never people — those are Social Lens's
consented domain). Recognition is a pluggable seam (a real NPU classifier or
a deterministic mock); the panel is assembled from providers, so the "hard
external integrations" (a laptop's recent files, a car's tire pressure) are
just callables you register. The built-in providers use only your own
on-device memory, and the whole lens is gated behind the Privacy Veil.

    from dreamlayer.object_lens import ObjectLens
    lens = ObjectLens(ring=my_ring)
    panel = lens.look(camera_frame)
    if panel:
        card = panel.to_hud_card()
"""
from .lens import ObjectLens
from .recognizer import ObjectRecognizer, PERSON_LABELS, DEFAULT_TAXONOMY
from .providers import (
    ProviderRegistry, PanelProvider, MemoryProvider, NoteProvider,
    LaptopProvider, CarProvider, PlantProvider, AIProvider,
)
from .polled import PolledSource, humanize_age
from .schema import ObjectSighting, ObjectPanel, PanelRow

__all__ = [
    "ObjectLens", "ObjectRecognizer", "PERSON_LABELS", "DEFAULT_TAXONOMY",
    "ProviderRegistry", "PanelProvider", "MemoryProvider", "NoteProvider",
    "LaptopProvider", "CarProvider", "PlantProvider", "AIProvider",
    "PolledSource", "humanize_age",
    "ObjectSighting", "ObjectPanel", "PanelRow",
]
