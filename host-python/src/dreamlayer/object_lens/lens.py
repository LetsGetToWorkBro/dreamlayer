"""object_lens/lens.py — the Object Lens: look at a thing, get a panel.

Ties recognition (recognizer.py) to panel assembly (providers.py):

    lens = ObjectLens(ring=ring)          # ships with MemoryProvider
    lens.registry.register(LaptopProvider(my_laptop_agent))
    panel = lens.look(camera_frame)       # None, or an ObjectPanel

Privacy: veiled means blind (allow_capture gate), a person is never panelled
(the recogniser defers to Social Lens), and the built-in providers read only
your own on-device memory. External data appears only through providers you
explicitly register.
"""
from __future__ import annotations

import time
from typing import Optional

from .recognizer import ObjectRecognizer
from .providers import ProviderRegistry, MemoryProvider
from .schema import ObjectPanel


class ObjectLens:
    def __init__(self, ring=None, recognizer: Optional[ObjectRecognizer] = None,
                 registry: Optional[ProviderRegistry] = None,
                 privacy=None, now_fn=None):
        self.recognizer = recognizer or ObjectRecognizer()
        self.registry = registry or ProviderRegistry()
        if ring is not None and registry is None:
            self.registry.register(MemoryProvider(ring))
        self._privacy = privacy or _AlwaysOn()
        self._now = now_fn or time.time

    def look(self, frame, now: Optional[float] = None) -> Optional[ObjectPanel]:
        """Recognise the object in view and build its panel, or None."""
        if not self._privacy.allow_capture():
            return None                       # veiled: blind
        sighting = self.recognizer.recognize(frame)
        if sighting is None:
            return None
        now = now if now is not None else self._now()
        panel = self.registry.build_panel(sighting, now=now)
        # a bare identification (no rows) is still a valid, useful panel:
        # "that's a mug" — so we return it even when empty.
        return panel


class _AlwaysOn:
    def allow_capture(self) -> bool:
        return True
