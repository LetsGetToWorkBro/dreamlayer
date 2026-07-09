"""Relationship graph (networkx) — who-knows-who + shared-event nodes.

ADD-alongside: brand-new file (no graph existed; relationships were flat per-
ContactRecord fields). Lazy-imports networkx (extras group `memory`); when
absent it falls back to a plain adjacency dict with the same query surface, so
"everyone I met at that conference" works either way.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.social_graph")

try:  # optional dep — extras group `memory`
    import networkx as nx  # type: ignore
    _HAS_NX = True
except ImportError:
    _HAS_NX = False


class RelationshipGraph:
    available = _HAS_NX

    def __init__(self):
        self._g = nx.Graph() if _HAS_NX else None
        self._adj: dict[str, set[str]] = {}   # fallback: person -> events
        self._events: dict[str, set[str]] = {}  # fallback: event -> people

    def add_person(self, contact_id: str, **attrs) -> None:
        if _HAS_NX:
            self._g.add_node(("p", contact_id), kind="person", **attrs)
        self._adj.setdefault(contact_id, set())

    def met_at(self, contact_id: str, event: str) -> None:
        """Record that a person was met at a shared event."""
        self.add_person(contact_id)
        if _HAS_NX:
            self._g.add_node(("e", event), kind="event")
            self._g.add_edge(("p", contact_id), ("e", event))
        self._adj[contact_id].add(event)
        self._events.setdefault(event, set()).add(contact_id)

    def relate(self, a: str, b: str, kind: str = "knows") -> None:
        self.add_person(a); self.add_person(b)
        if _HAS_NX:
            self._g.add_edge(("p", a), ("p", b), kind=kind)
        self._adj[a].add(f"~{b}")
        self._adj[b].add(f"~{a}")

    def people_at(self, event: str) -> list[str]:
        """Everyone met at a given shared event."""
        if _HAS_NX:
            node = ("e", event)
            if node not in self._g:
                return []
            return [n[1] for n in self._g.neighbors(node) if n[0] == "p"]
        return sorted(self._events.get(event, set()))

    def connections(self, contact_id: str) -> list[str]:
        """Other people directly related to this contact."""
        if _HAS_NX:
            node = ("p", contact_id)
            if node not in self._g:
                return []
            return [n[1] for n in self._g.neighbors(node) if n[0] == "p"]
        return sorted(x[1:] for x in self._adj.get(contact_id, set()) if x.startswith("~"))
