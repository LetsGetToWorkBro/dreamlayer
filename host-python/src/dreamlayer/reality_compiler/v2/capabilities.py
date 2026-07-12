"""v2/capabilities.py — the emit→reaction capability registry.

A running lens can emit a small tag; some tags ask the host to *do* something
and stream the result back onto the glass — run the Brain over a spoken
question (``ask``), turn the words you hear into your language (``translate``),
name what the camera sees (``look``). Each such reaction is a **capability**:
a named host-side power a lens must declare in ``requires`` to use.

This replaces the old hard-coded ``if tag == "ask"`` seam with an explicit,
auditable contract:

  * the validator refuses a lens that emits a capability tag it never
    declared, so ``requires`` can't silently drift from what the lens does;
  * the gallery can show exactly which powers a lens asks for, *before* you
    run it — the same way plugin manifests already surface ``requires``;
  * the runtime only fires a reaction the active lens declared, so a forged
    figment that skipped the gate still can't invoke a power it never asked
    for (defense in depth, mirroring the emit token bucket).

Capability *handlers* (the code that actually answers/translates) live
host-side because they need the Brain. This module is the pure declaration
and lookup, so the validator and the wire layer can share it without
importing the server. A lens may also declare a capability it consumes
*passively* — the Brain pushing a translation into a ``{slot:...}`` with no
figment emit at all (the Rosetta lens) — hence declared ⊇ emitted, not ==.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .figment import Figment


@dataclass(frozen=True)
class Capability:
    """A named host power. ``name`` doubles as the emit tag that invokes it."""
    name: str
    summary: str          # one line, user-facing (gallery / manifest)
    passive: bool = False  # fed by the Brain into a slot, no figment emit


# The built-in reactions. Adding a capability = one entry here + (for an
# active reaction) a handler the host registers. A tag NOT listed here is a
# *free* local emit — a rep/round/beat ledger mark, a plugin's own signal,
# ``banished`` — that needs no declared power and gets no built-in reaction.
CAPABILITIES: dict[str, Capability] = {
    "ask": Capability(
        "ask", "answer a spoken question from your own memory (or the cloud, "
        "if you allow it)"),
    "translate": Capability(
        "translate", "turn the words you hear into your language", passive=True),
    "look": Capability(
        "look", "name what the camera is looking at"),
}


def capability_for(tag: Optional[str]) -> Optional[str]:
    """The capability a tag invokes, or None if it's a free/local emit."""
    if tag and tag in CAPABILITIES:
        return tag
    return None


def declared_requires(fig: "Figment") -> list[str]:
    """Capabilities a lens declares (``meta['requires']``), sorted and deduped.
    Unknown/garbage entries are dropped here so callers see only real ones —
    the validator reports them separately."""
    raw = (fig.meta or {}).get("requires", []) or []
    seen = {r for r in raw if isinstance(r, str) and r in CAPABILITIES}
    return sorted(seen)


def emitted_capabilities(fig: "Figment") -> list[str]:
    """Capabilities the lens actively invokes, inferred from its emit tags."""
    seen: set[str] = set()
    for scene in fig.scenes.values():
        for t in list(scene.on.values()) + list(scene.on_timeout):
            cap = capability_for(t.emit)
            if cap:
                seen.add(cap)
    return sorted(seen)


def unknown_requires(fig: "Figment") -> list[str]:
    """Declared ``requires`` entries that are not real capabilities."""
    raw = (fig.meta or {}).get("requires", []) or []
    return sorted({r for r in raw
                   if not (isinstance(r, str) and r in CAPABILITIES)})


def require(fig: "Figment", *caps: str) -> "Figment":
    """Declare that a lens needs these capabilities. Rides in ``meta`` and so
    in the signed canonical JSON — call before keep()/sign(). Idempotent."""
    have = list((fig.meta or {}).get("requires", []) or [])
    for c in caps:
        if c not in have:
            have.append(c)
    fig.meta = dict(fig.meta or {})
    fig.meta["requires"] = have
    return fig
