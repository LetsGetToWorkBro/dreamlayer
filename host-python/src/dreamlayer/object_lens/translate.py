"""object_lens/translate.py — Rosetta as an Object Lens provider.

When you look at something with foreign text on it (a menu, a sign, a
package), the recogniser puts that text in the sighting's `text` attribute;
this provider runs it through the Rosetta Lens and adds the meaning as a
panel row. Inert when there's no text or no translation model wired.
"""
from __future__ import annotations

from .providers import PanelProvider
from .schema import PanelRow


class RosettaProvider(PanelProvider):
    name = "rosetta"

    def __init__(self, rosetta, target: str = "en"):
        self._rosetta = rosetta
        self._target = target

    def matches(self, sighting) -> bool:
        return bool((sighting.attributes or {}).get("text"))

    def build(self, sighting, now=None) -> list[PanelRow]:
        text = (sighting.attributes or {}).get("text", "")
        res = self._rosetta.read(text, target=self._target)
        if not res.changed():
            return []                         # already the target, or no model
        return [PanelRow(label=f"{res.source_lang}→{res.target_lang}",
                         detail=res.translated, kind="info", source=self.name)]
