"""object_lens/providers.py — where a panel's rows come from.

A panel is assembled, not hard-coded. Each PanelProvider decides whether it
applies to a sighting and, if so, contributes rows. Two kinds ship:

  on-device, privacy-safe (work today)
    MemoryProvider  — what *you* already know about this object: have you
                      seen it before, where, do you own one. Your data only.
    NoteProvider    — reminders/notes you anchored to this kind of object.

  integration seams (the "hard external" part, cleanly abstracted)
    LaptopProvider / CarProvider / PlantProvider — each takes an injected
    data_source callable. That's the whole seam: wire a real integration
    (a companion agent reading recent files, an OBD dongle, a soil sensor)
    to the callable and the panel fills in. The demo passes a fixed source.

The registry merges the matching providers' rows into one ObjectPanel.
"""
from __future__ import annotations

from typing import Callable, Optional

from .schema import ObjectSighting, PanelRow, ObjectPanel


class PanelProvider:
    name = "provider"

    def matches(self, sighting: ObjectSighting) -> bool:
        raise NotImplementedError

    def build(self, sighting: ObjectSighting,
              now: Optional[float] = None) -> list[PanelRow]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# On-device, privacy-safe
# ---------------------------------------------------------------------------

class MemoryProvider(PanelProvider):
    """Your own memory of this object: prior sightings, place, ownership."""
    name = "memory"

    def __init__(self, ring, lookback: int = 200):
        self.ring = ring
        self.lookback = lookback

    def matches(self, sighting: ObjectSighting) -> bool:
        return True                           # every object gets a memory row

    def build(self, sighting, now=None) -> list[PanelRow]:
        key = sighting.key()
        seen = []
        owned = False
        for b in self.ring.latest(limit=self.lookback):
            ev = b.event
            meta = getattr(ev, "meta", None) or {}
            if meta.get("private"):
                continue                      # private sightings never surface
            summary = (getattr(ev, "summary", "") or "").lower()
            label = str(meta.get("object", "")).lower()
            if key in summary or key == label:
                seen.append((b.ts, ev, meta))
                if meta.get("owned") or "bought" in summary or "my " + key in summary:
                    owned = True
        rows: list[PanelRow] = []
        if seen:
            seen.sort(key=lambda s: -s[0])
            last_meta = seen[0][2]
            place = last_meta.get("place") or last_meta.get("location") or ""
            rows.append(PanelRow(
                label="seen before",
                detail=(f"{len(seen)}× · last at {place}" if place
                        else f"{len(seen)}× before"),
                kind="info", source=self.name))
            if owned:
                rows.append(PanelRow(label="you already own this",
                                     kind="info", source=self.name))
        return rows


class NoteProvider(PanelProvider):
    """Reminders/notes you anchored to a kind of object.

    notes: dict {object_key: [str, …]} or a callable(key) -> [str, …].
    """
    name = "note"

    def __init__(self, notes):
        self._notes = notes

    def _for(self, key: str) -> list[str]:
        if callable(self._notes):
            return list(self._notes(key) or [])
        return list((self._notes or {}).get(key, []))

    def matches(self, sighting) -> bool:
        return bool(self._for(sighting.key()))

    def build(self, sighting, now=None) -> list[PanelRow]:
        return [PanelRow(label="reminder", detail=note, kind="info",
                         source=self.name)
                for note in self._for(sighting.key())]


# ---------------------------------------------------------------------------
# Integration seams — inject a data_source() to make these real
# ---------------------------------------------------------------------------

class _SourceProvider(PanelProvider):
    """A provider whose rows come from an injected data source callable.

    matches a set of object keys; data_source() returns a dict the subclass
    turns into rows. This is the seam a real integration plugs into.
    """
    keys: frozenset = frozenset()

    def __init__(self, data_source: Callable[[], dict]):
        self._source = data_source

    def matches(self, sighting) -> bool:
        return sighting.key() in self.keys

    def _rows(self, data: dict) -> list[PanelRow]:
        raise NotImplementedError

    def build(self, sighting, now=None) -> list[PanelRow]:
        try:
            data = self._source() or {}
        except Exception:
            return []
        return self._rows(data)


class LaptopProvider(_SourceProvider):
    name = "laptop"
    keys = frozenset({"laptop", "computer", "macbook"})

    def _rows(self, data):
        rows = []
        for f in (data.get("recent_files") or [])[:3]:
            rows.append(PanelRow(label="recent", detail=str(f),
                                 kind="action", source=self.name))
        if "battery" in data:
            rows.append(PanelRow(label="battery", value=f"{data['battery']}%",
                                 kind="stat", source=self.name))
        return rows


class CarProvider(_SourceProvider):
    name = "car"
    keys = frozenset({"car", "vehicle"})

    def _rows(self, data):
        rows = []
        tp = data.get("tire_pressure")
        if tp is not None:
            rows.append(PanelRow(label="tire pressure", value=f"{tp} psi",
                                 kind="stat", source=self.name))
        if "fuel" in data:
            rows.append(PanelRow(label="fuel", value=f"{data['fuel']}%",
                                 kind="stat", source=self.name))
        return rows


class PlantProvider(_SourceProvider):
    name = "plant"
    keys = frozenset({"houseplant", "plant"})

    def _rows(self, data):
        rows = []
        if "last_watered" in data:
            rows.append(PanelRow(label="last watered",
                                 detail=str(data["last_watered"]),
                                 kind="info", source=self.name))
        if data.get("needs_water"):
            rows.append(PanelRow(label="needs water", kind="action",
                                 source=self.name))
        return rows


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ProviderRegistry:
    def __init__(self, providers: Optional[list[PanelProvider]] = None):
        self._providers: list[PanelProvider] = list(providers or [])

    def register(self, provider: PanelProvider) -> None:
        self._providers.append(provider)

    def build_panel(self, sighting: ObjectSighting,
                    now: Optional[float] = None) -> ObjectPanel:
        rows: list[PanelRow] = []
        sources: list[str] = []
        for prov in self._providers:
            try:
                if not prov.matches(sighting):
                    continue
                prov_rows = prov.build(sighting, now=now) or []
            except Exception:
                continue
            if prov_rows:
                rows.extend(prov_rows)
                if prov.name not in sources:
                    sources.append(prov.name)
        subtitle = ""
        brand = sighting.attributes.get("brand") or sighting.attributes.get("color")
        if brand:
            subtitle = str(brand)
        return ObjectPanel(sighting=sighting, title=sighting.label,
                           subtitle=subtitle, rows=rows, sources=sources)
