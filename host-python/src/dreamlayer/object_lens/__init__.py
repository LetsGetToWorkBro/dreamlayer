"""object_lens — Oracle: look at anything, know it.

Display name: **Oracle** (the World lens's flagship — "look at anything and
it tells you what it is"). The code stays `object_lens` / `ObjectLens`.


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
from .label import LabelProvider, ShoppingProvider, DietaryProfile
from .translate import RosettaProvider
from .polled import PolledSource, humanize_age
from .schema import ObjectSighting, ObjectPanel, PanelRow

__all__ = [
    "ObjectLens", "ObjectRecognizer", "PERSON_LABELS", "DEFAULT_TAXONOMY",
    "ProviderRegistry", "PanelProvider", "MemoryProvider", "NoteProvider",
    "LaptopProvider", "CarProvider", "PlantProvider", "AIProvider",
    "LabelProvider", "ShoppingProvider", "DietaryProfile", "RosettaProvider",
    "PolledSource", "humanize_age",
    "ObjectSighting", "ObjectPanel", "PanelRow",
]
