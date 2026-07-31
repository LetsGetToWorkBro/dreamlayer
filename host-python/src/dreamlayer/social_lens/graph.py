"""Relationship graph (networkx) — who-knows-who + shared-event nodes.

ADD-alongside: brand-new file (no graph existed; relationships were flat per-
ContactRecord fields). Lazy-imports networkx (extras group `memory`); when
absent it falls back to a plain adjacency dict with the same query surface, so
"everyone I met at that conference" works either way.

THE THREE QUERIES NETWORKX ACTUALLY EARNS. For a long time this class held only
`people_at` and `connections` — both of which the fallback dict answers just as
well, so installing networkx bought the wearer nothing. The capability's own
promise is "paths, mutual friends, communities", and none of the three existed.
They do now, and each is explicit about which engine answered:

  * `mutual(a, b)`   — cheap either way (set intersection over neighbours).
  * `path(a, b)`     — a BFS, so also honest without networkx; the win is that
                       nx does it over the same graph the other queries use
                       rather than a second hand-rolled structure.
  * `communities()`  — the one that genuinely needs it. With networkx this is
                       greedy modularity (clusters that are densely connected
                       INSIDE and sparse between). Without, the only honest
                       answer is connected components, which is a much weaker
                       claim — two cliques joined by one acquaintance are one
                       component and two communities. `communities_engine()`
                       says which you got, so no caller reports the strong
                       answer when it computed the weak one.
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
        # A self-relation is refused AT THE DOOR rather than filtered out of every
        # query downstream. `relate(x, x)` makes a self-loop, which is not a
        # relationship anyone has — it reads as "x has x in common with x" and it
        # inflates x's degree in the community split. Guarding here let `mutual`
        # drop a pair-exclusion filter that was unreachable any other way; a
        # mutation deleting that filter survived every test, which is how it was
        # found to be dead code rather than a safeguard.
        if not a or not b or a == b:
            self.add_person(a or b)
            return
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

    # -- the queries a graph is FOR -------------------------------------------

    def people(self) -> list:
        """Every person in the graph."""
        if _HAS_NX:
            return sorted(n[1] for n in self._g.nodes if n[0] == "p")
        return sorted(self._adj)

    def events(self) -> list:
        """Every shared event in the graph."""
        if _HAS_NX:
            return sorted(n[1] for n in self._g.nodes if n[0] == "e")
        return sorted(self._events)

    def _neighbours(self, contact_id: str) -> set:
        """People AND events adjacent to a person — the raw adjacency both
        `mutual` and `path` walk. Kept private and typed as ("p"|"e", id) pairs so
        a person named the same as an event can never be confused for it."""
        if _HAS_NX:
            node = ("p", contact_id)
            if node not in self._g:
                return set()
            return set(self._g.neighbors(node))
        out: set = set()
        for x in self._adj.get(contact_id, set()):
            out.add(("p", x[1:]) if x.startswith("~") else ("e", x))
        return out

    def mutual(self, a: str, b: str) -> dict:
        """What two people have in COMMON — shared acquaintances and shared events.

        Two kinds, reported separately, because they mean different things to a
        person reading them: "you both know Priya" is a social fact, "you were both
        at the Acme launch" is a where-from fact. Collapsing them into one list
        loses the only thing that makes the answer useful.
        """
        if a == b:
            return {"people": [], "events": []}
        na, nb = self._neighbours(a), self._neighbours(b)
        both = na & nb
        # No pair-exclusion filter, and that is deliberate rather than an omission:
        # for `a` to be its own mutual connection it would have to be its own
        # neighbour, which only a self-loop can arrange — and `relate` refuses to
        # make one. `b` is a neighbour of `a` when they know each other directly,
        # but never of itself, so it cannot survive the intersection either.
        return {
            "people": sorted(n[1] for n in both if n[0] == "p"),
            "events": sorted(n[1] for n in both if n[0] == "e"),
        }

    def path(self, a: str, b: str, max_hops: int = 6) -> list:
        """How you know someone: the shortest chain from `a` to `b`, or [].

        Returned as TYPED steps — [{"kind": "person"|"event", "id": …}] — rather
        than bare strings. A chain reads "Marcus → (the Acme launch) → Priya", and
        which of those is a person and which is a room is the whole meaning; a list
        of strings would leave the caller guessing from context.

        `max_hops` is a real bound, not decoration: a six-degrees chain is already
        past the point of being an explanation, and an address-book-sized graph
        (`sync_contacts` can write hundreds of people) makes an unbounded search a
        free way to spend CPU on an answer nobody can use.
        """
        if not a or not b or a == b:
            return []
        start, goal = ("p", a), ("p", b)
        if _HAS_NX:
            if start not in self._g or goal not in self._g:
                return []
            try:
                raw = nx.shortest_path(self._g, start, goal)
            except Exception:                     # noqa: BLE001 — nx.NetworkXNoPath
                return []
            # Hops are EDGES, so a path of n nodes is n-1 hops; an over-long chain
            # is dropped rather than truncated, because half a chain is not a
            # shorter explanation, it is a wrong one.
            if len(raw) - 1 > max_hops:
                return []
        else:
            raw = self._bfs(start, goal, max_hops)
            if not raw:
                return []
        return [{"kind": "person" if k == "p" else "event", "id": i}
                for k, i in raw]

    def _bfs(self, start, goal, max_hops: int) -> list:
        """Shortest path without networkx. Breadth-first, so the FIRST time the
        goal is reached is by a shortest route — a depth-first walk would return
        some path and call it the shortest."""
        from collections import deque
        if start[1] not in self._adj or goal[1] not in self._adj:
            return []
        seen = {start}
        q = deque([[start]])
        while q:
            chain = q.popleft()
            if len(chain) - 1 >= max_hops:
                continue
            node = chain[-1]
            for nxt in sorted(self._step(node)):
                if nxt in seen:
                    continue
                if nxt == goal:
                    return chain + [nxt]
                seen.add(nxt)
                q.append(chain + [nxt])
        return []

    def _step(self, node) -> set:
        """Neighbours of a person OR an event node, fallback mode."""
        kind, ident = node
        if kind == "p":
            return self._neighbours(ident)
        return {("p", p) for p in self._events.get(ident, set())}

    def communities_engine(self) -> str:
        """Which algorithm `communities()` will use: "modularity" (networkx) or
        "components" (the weaker fallback). Exposed so no caller reports the
        strong answer while holding the weak one."""
        return "modularity" if _HAS_NX else "components"

    def communities(self) -> list:
        """Clusters of people who mostly know each other.

        With networkx this is greedy modularity maximisation: a cluster is dense
        inside and sparse outside, which is what "community" means. Without it the
        answer is connected components — genuinely weaker, and worth naming: two
        separate circles joined by a single mutual acquaintance are ONE component
        and TWO communities. Events are dropped from the result either way; a
        conference is not a member of a friendship group, it is the thing that
        connected one.
        """
        if _HAS_NX:
            try:
                from networkx.algorithms.community import (  # type: ignore
                    greedy_modularity_communities)
                groups = greedy_modularity_communities(self._g)
            except Exception:                     # noqa: BLE001 — empty graph / no algo
                groups = list(nx.connected_components(self._g)) if len(self._g) else []
            out = []
            for g in groups:
                people = sorted(n[1] for n in g if n[0] == "p")
                if people:
                    out.append(people)
            return sorted(out, key=lambda g: (-len(g), g[0] if g else ""))
        # fallback: connected components over the person+event adjacency
        seen: set = set()
        out = []
        for person in sorted(self._adj):
            if person in seen:
                continue
            stack, group = [person], []
            seen.add(person)
            while stack:
                cur = stack.pop()
                group.append(cur)
                for kind, ident in self._neighbours(cur):
                    if kind == "p":
                        if ident not in seen:
                            seen.add(ident)
                            stack.append(ident)
                    else:
                        for other in self._events.get(ident, set()):
                            if other not in seen:
                                seen.add(other)
                                stack.append(other)
            out.append(sorted(group))
        return sorted(out, key=lambda g: (-len(g), g[0] if g else ""))
