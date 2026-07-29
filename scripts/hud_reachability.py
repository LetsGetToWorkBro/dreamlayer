#!/usr/bin/env python3
"""Which declared HUD cards can the shipped Brain actually produce and draw?

`demo/catalog.py` declares the product's HUD features — the 24 cards the demo
film walks through, and the ones the landing page and the gitbook promise. Each
maps to a real builder in `hud/cards.py`. That mapping is where a card can quietly
become a lie, in two different directions:

  * NO PRODUCER. The builder exists and the demo calls it, but nothing the
    shipped Brain can reach ever does. The card is real in a film and
    unreachable in the product — the same class of gap `lens_reachability.py`
    found for a dozen lenses, and the one `decisions/0001` is about.
  * NO GLASS PATH. Something produces it, but `halo-lua`'s renderer has no
    branch for its `type`, so on the actual hardware it draws as a generic
    fallback or not at all. Note what the fallbacks drop: every shipped generic
    renderer draws `primary` (+ sometimes `detail`) and DISCARDS `footer` — and
    `footer` is where `ConsistencyCard` puts the prior statement, i.e. Candor's
    entire proposition. "It renders something" is not "it renders the card".

Both halves are checked, because either alone is satisfiable while the wearer
sees nothing. A card is DONE when it has a producer in the Brain's import
closure AND a renderer branch on the glass.

WHAT THIS PROVES, AND WHAT IT DOES NOT. Same honest limits as its sibling: a
producer call site in the closure means the code CAN run, not that it does —
`RetentionSweep` was importable for years while nothing called it, and
`BrainLenses` was constructible for a release while nothing built one. Read a
clean run as "no card is structurally unreachable", never as "every card
appears in front of a wearer".

    $ python3 scripts/hud_reachability.py
    $ python3 scripts/hud_reachability.py --verbose    # show producers per card
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PKG = "dreamlayer"
SRC = ROOT / "host-python" / "src" / PKG
LUA = ROOT / "halo-lua"


def _lens_module():
    """Reuse the import-closure walker rather than growing a second one.

    Two graph builders that are supposed to agree is one more thing to keep in
    step, and the relative-import arithmetic in there was got wrong twice
    before it was right. Imported by path because `scripts/` is not a package.
    """
    spec = importlib.util.spec_from_file_location(
        "_lens_reachability", HERE / "lens_reachability.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# what the product declares
# --------------------------------------------------------------------------

def _declared_features() -> list[tuple[str, str, str]]:
    """(id, title, ALL_SAMPLES key) for every `Feature(...)` in demo/catalog.py."""
    tree = ast.parse((SRC / "demo" / "catalog.py").read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Feature":
            args = [a.value if isinstance(a, ast.Constant) else None
                    for a in node.args]
            if len(args) >= 4:
                out.append((args[0], args[1], args[3]))
    return out


def _sample_builders() -> dict[str, str]:
    """ALL_SAMPLES key → the `hud.cards` function that builds it.

    The dict's values are literally calls to the real builders — the module's
    own docstring says the samples are "always the actual renderer output" —
    so the AST gives the mapping with no guessing.
    """
    tree = ast.parse((SRC / "hud" / "cards.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if getattr(node.target, "id", "") != "ALL_SAMPLES":
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        out = {}
        for k, v in zip(node.value.keys, node.value.values):
            if not isinstance(k, ast.Constant):
                continue
            fn = v.func if isinstance(v, ast.Call) else None
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name:
                out[k.value] = name
        return out
    return {}


def _card_types() -> dict[str, str]:
    """`hud.cards` function name → the `"type"` string its dict carries.

    That string is the contract with the glass: `renderer.lua` branches on
    `card.type`, so it is the only thing that decides whether the hardware has
    a real drawing for this card or falls through to a generic one.
    """
    tree = ast.parse((SRC / "hud" / "cards.py").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "type"
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)):
                    out.setdefault(fn.name, v.value)
    return out


# --------------------------------------------------------------------------
# who can produce them
# --------------------------------------------------------------------------

def _producers(reachable: set, builders: set) -> dict[str, set]:
    """builder name → the reachable modules that CALL it.

    THREE exclusions, and every one of them is load-bearing — with any of them
    missing this check passes on a product where no card ever fires:

      * `hud/cards.py` itself. `ALL_SAMPLES` is a dict of literal calls to every
        builder in the file, so the defining module "produces" all 34 of them.
        A first run of this script reported 0 cards without a producer for
        exactly that reason; a module calling itself to build its own fixtures
        is not a caller.
      * `demo/`. Drawing every card is its whole job.
      * `simulator/`. Same, for the desktop stand-in.

    What is left is code a wearer's Brain can actually run.
    """
    lens = _lens_module()
    cards_mod = f"{PKG}.hud.cards"
    out: dict[str, set] = {b: set() for b in builders}
    for path in lens._sources():
        mod = lens._module_name(path)
        if mod not in reachable or mod == cards_mod:
            continue
        if any(part in ("demo", "simulator") for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name in out:
                out[name].add(mod)
    return out


# The renderer names a card type two ways, and BOTH are a real drawing:
#   `if card.type == "FactCheckCard"`      — a quoted comparison
#   `CommitmentDriftCard = function(...)`  — an entry in the DRAW dispatch table
# An earlier draft matched only the quoted form and reported seven cards as
# undrawable that `renderer.lua` has had dedicated drawing functions for all
# along. A checker that cries wolf on a third of the catalogue gets ignored,
# which is worse than not having one.
#
# The table form requires `= function`, not any `XCard = …`. Lua has other
# tables keyed by card type that say nothing about drawing — `main.lua` maps
# every type to a queue class, including `PaletteShiftCard`, which `cards.py`
# documents in as many words as "a palette command carrier, not a drawable
# card". Accepting a bare `=` marked it drawn on the strength of a priority
# table.
_LUA_QUOTED = re.compile(r'["\']([A-Za-z]+Card)["\']')
_LUA_DRAW_ENTRY = re.compile(r'^\s*([A-Za-z]+Card)\s*=\s*function', re.MULTILINE)
_LUA_COMMENT = re.compile(r'^\s*--.*$', re.MULTILINE)


def _drawn_on_glass() -> set:
    """Card `type` strings `halo-lua` has a real drawing for.

    Read off every .lua rather than only `renderer.lua`: `stasis.lua` and
    `dream_renderer.lua` own their own card families, and a card drawn by a
    sibling module is drawn. Comments are stripped first — `renderer.lua`
    labels each drawing function with a `-- XCard` banner and lists card names
    in its header, so leaving them in would mark a type as drawn on the
    strength of a section heading.
    """
    seen: set = set()
    if not LUA.exists():
        return seen
    for path in LUA.rglob("*.lua"):
        try:
            body = _LUA_COMMENT.sub("", path.read_text(encoding="utf-8"))
        except OSError:
            continue
        seen |= set(_LUA_QUOTED.findall(body))
        seen |= set(_LUA_DRAW_ENTRY.findall(body))
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true",
                    help="list the Brain-side modules that produce each card")
    args = ap.parse_args()

    lens = _lens_module()
    files = lens._sources()
    known = {lens._module_name(p) for p in files}
    _roots, reachable = lens._closure(lens._import_graph(files), known)

    features = _declared_features()
    samples = _sample_builders()
    types = _card_types()
    producers = _producers(reachable, set(samples.values()))
    drawn = _drawn_on_glass()

    print(f"{len(features)} declared HUD features · {len(samples)} sample cards · "
          f"{len(drawn)} card types drawn on glass")

    no_producer, no_glass, ok = [], [], []
    for fid, title, key in features:
        builder = samples.get(key)
        ctype = types.get(builder or "", "")
        made = producers.get(builder or "", set())
        if not made:
            no_producer.append((title, key, builder, ctype))
        elif ctype and ctype not in drawn:
            no_glass.append((title, key, builder, ctype))
        else:
            ok.append((title, key, builder, ctype, made))

    print(f"\nNO BRAIN-SIDE PRODUCER ({len(no_producer)}) — the demo can draw "
          f"these and the product cannot")
    for title, key, builder, ctype in sorted(no_producer):
        print(f"  {title:28} {key:20} {builder or '?'}()  {ctype}")

    print(f"\nNO GLASS RENDERER ({len(no_glass)}) — produced, but halo-lua has "
          f"no branch for the type; a generic fallback DROPS the footer")
    for title, key, builder, ctype in sorted(no_glass):
        print(f"  {title:28} {key:20} {ctype}")

    print(f"\nreachable on both surfaces ({len(ok)})")
    for title, key, builder, ctype, made in sorted(ok):
        via = ("   via " + ", ".join(sorted(m.replace(PKG + ".", "")
                                            for m in made)[:3])) if args.verbose else ""
        print(f"  {title:28} {ctype}{via}")

    return 1 if (no_producer or no_glass) else 0


if __name__ == "__main__":
    sys.exit(main())
