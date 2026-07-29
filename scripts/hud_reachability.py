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


def _inline_card_types(reachable: set) -> dict[str, set]:
    """card type → reachable modules that build a card dict OUTSIDE `hud/cards.py`.

    The 24 features come from `demo/catalog.py`, so a card the Brain pushes but
    the demo never lists is INVISIBLE to every bucket above. That is not
    hypothetical: `orchestrator/consistency.py:_consistency_card` builds a
    `ConsistencyCard` inline, the Brain's Candor lens pushes it on a live path,
    and it appeared in no category of this report — while having no drawing in
    `halo-lua` OR the Live Lens, which made it the most badly-degraded card in
    the product and the only one nothing measured.

    Same three exclusions as `_producers`, for the same reasons.
    """
    lens = _lens_module()
    cards_mod = f"{PKG}.hud.cards"
    out: dict[str, set] = {}
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
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "type"
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)
                        and v.value.endswith("Card")):
                    out.setdefault(v.value, set()).add(mod)
    return out


# Card types the Brain demonstrably pushes but `_pushed_types` cannot NAME,
# because the push site's card expression defeats a one-hop AST resolver. Both
# entries are verified by reading the call site, and both are listed here rather
# than left silent so the resolver's blind spot is data instead of a gap:
#
#   * ConsistencyCard  — lens_hosts.py:492 `self._push("candor", r.card)`. The
#     card is an ATTRIBUTE of the engine's result dataclass; naming it would
#     need real type inference, not a name lookup.
#   * QuestRewardCard  — lens_hosts.py:601 `card = reward.to_hud_card()`. The
#     method name is defined nine times across the tree with a different card
#     type each, so `_fn_card_types` deliberately refuses to resolve it.
_BRAIN_ONLY_PUSHED = frozenset({"ConsistencyCard", "QuestRewardCard"})


def _fn_card_types(reachable: set) -> dict[str, str]:
    """function name → the card type it returns, across every reachable module.

    Covers both shapes in the tree: a function whose body contains a literal
    ``"type": "XCard"`` dict, and one that returns a `hud.cards` builder call.

    Keyed by BARE NAME, because a push site calls these as `self._stasis_card` /
    `cards.saved_memory` / `reward.to_hud_card` and the attribute is all the AST
    gives us without real type inference. That is sound only where the name is
    unique, and one name is emphatically not: `to_hud_card` is defined NINE
    times across the tree, returning a different card type each time. A first
    version of this resolver keyed on it blindly and reported `QuestRewardCard`
    as never-pushed and `WaypathCard` as pushed — both exactly backwards, from
    whichever definition `ast.walk` happened to reach first.

    So a name that resolves to more than one card type maps to ``""`` and stops
    resolving. Its push sites are then counted as UNRESOLVED and printed as
    such. An honest unknown is the only safe answer here; guessing produces
    confident nonsense in both directions.
    """
    lens = _lens_module()
    builder_types = _card_types()
    out: dict[str, str] = dict(builder_types)
    seen: dict[str, set] = {k: {v} for k, v in builder_types.items()}
    for path in lens._sources():
        if lens._module_name(path) not in reachable:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                found = ""
                if isinstance(node, ast.Dict):
                    for k, v in zip(node.keys, node.values):
                        if (isinstance(k, ast.Constant) and k.value == "type"
                                and isinstance(v, ast.Constant)
                                and str(v.value).endswith("Card")):
                            found = v.value
                elif isinstance(node, ast.Return) and isinstance(node.value, ast.Call):
                    nm = (getattr(node.value.func, "id", None)
                          or getattr(node.value.func, "attr", None))
                    found = builder_types.get(nm or "", "")
                if found:
                    seen.setdefault(fn.name, set()).add(found)
    for name, kinds in seen.items():
        out[name] = kinds.pop() if len(kinds) == 1 else ""
    return out


def _pushed_types(reachable: set) -> dict[str, set]:
    """card type → reachable modules that PUSH it to the glass.

    The distinction this makes is the one the whole audit turns on. Nine of the
    ten undeclared types are built and returned as JSON to the phone, where
    every field survives — they are not degraded by a generic renderer because
    they never meet one. Only the types handed to `_push` / `push_event` land on
    the Live Lens, and only those can be gutted by it. Reporting "built" as if
    it meant "pushed" would have manufactured seven defects that do not exist.

    Resolution is deliberately one hop: a direct builder call, or a local name
    assigned from one earlier in the same function. Both shapes occur; anything
    deeper is reported as unresolved rather than guessed at.
    """
    lens = _lens_module()
    fn_types = _fn_card_types(reachable)
    out: dict[str, set] = {}
    unresolved: list[str] = []
    for path in lens._sources():
        mod = lens._module_name(path)
        if mod not in reachable:
            continue
        if any(part in ("demo", "simulator") for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            assigns: dict[str, ast.AST] = {}
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    tgt = node.targets[0]
                    if isinstance(tgt, ast.Name):
                        assigns.setdefault(tgt.id, node.value)

            def _resolve(expr, depth=0):
                if depth > 1 or expr is None:
                    return ""
                if isinstance(expr, ast.Call):
                    nm = (getattr(expr.func, "id", None)
                          or getattr(expr.func, "attr", None))
                    return fn_types.get(nm or "", "")
                if isinstance(expr, ast.Name):
                    return _resolve(assigns.get(expr.id), depth + 1)
                return ""

            if fn.name in ("_push", "push_event"):
                continue          # the fan-out inside the pusher, not a push site
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                nm = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if nm not in ("_push", "push_event"):
                    continue
                arg = node.args[1] if len(node.args) >= 2 else next(
                    (k.value for k in node.keywords if k.arg == "card"), None)
                if arg is None:
                    continue      # no card slot at all — a same-named method on
                                  # something else (brain_rc's deployer), not ours
                ctype = _resolve(arg)
                if ctype:
                    out.setdefault(ctype, set()).add(mod)
                else:
                    unresolved.append(f"{mod.replace(PKG + '.', '')}:{node.lineno}")
    return out, unresolved


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

    THIS IS THE DEVICE'S RENDERER, AND THE BRAIN CANNOT REACH IT. See
    `_drawn_on_live_lens` below — that distinction is the whole reason this
    function is no longer the answer on its own.
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


# `renderEvent`'s dispatch in the Live Lens page: `t === "XCard"` comparisons.
_JS_DISPATCH = re.compile(r't\s*===\s*["\']([A-Za-z]+Card)["\']')


def _drawn_on_live_lens() -> set:
    """Card types the LIVE LENS has a bespoke drawing for — the surface the
    Brain actually reaches.

    An earlier draft of this script checked only `halo-lua` and reported all 24
    declared cards as having a renderer. That was measuring the wrong glass.
    `Brain.push_event` "fans a card out to every connected Live Lens" — an SSE
    stream to the browser page in `ai_brain/server/live.py`. Nothing under
    `ai_brain/` calls `bridge.send_card`, so no Brain push has any path to the
    glasses firmware at all; halo-lua is the ORCHESTRATOR's renderer.

    The two disagree sharply, which is the point: `renderEvent` has bespoke
    branches for a handful of types and sends everything else to
    `glassEventCard`, which draws `eyebrow` and `primary` AND NOTHING ELSE. So
    a card whose answer lives in another field — `object_recall` puts the place
    there, `ConsistencyCard` puts the prior statement in `footer` — arrives
    gutted. "It renders something" is not "it renders the card", and counting
    the fallback as a renderer is how a checker starts agreeing with itself.
    """
    p = SRC / "ai_brain" / "server" / "live.py"
    try:
        body = p.read_text(encoding="utf-8")
    except OSError:
        return set()
    return set(_JS_DISPATCH.findall(body))


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
    device = _drawn_on_glass()
    live = _drawn_on_live_lens()

    print(f"{len(features)} declared HUD features · {len(samples)} sample cards")
    print(f"renderers: {len(device)} types drawn by halo-lua (the DEVICE, reached "
          f"by the Orchestrator) · {len(live)} by the Live Lens (the only surface "
          f"a Brain push reaches)")

    no_producer, no_device, gutted, ok = [], [], [], []
    for fid, title, key in features:
        builder = samples.get(key)
        ctype = types.get(builder or "", "")
        made = producers.get(builder or "", set())
        if not made:
            no_producer.append((title, key, builder, ctype))
        elif ctype and ctype not in device:
            no_device.append((title, key, builder, ctype))
        elif ctype and ctype not in live:
            gutted.append((title, key, builder, ctype, made))
        else:
            ok.append((title, key, builder, ctype, made))

    print(f"\nNO BRAIN-SIDE PRODUCER ({len(no_producer)}) — the demo can draw "
          f"these and the product cannot")
    for title, key, builder, ctype in sorted(no_producer):
        print(f"  {title:28} {key:20} {builder or '?'}()  {ctype}")

    print(f"\nNO DEVICE RENDERER ({len(no_device)}) — produced, but halo-lua has "
          f"no drawing for the type")
    for title, key, builder, ctype in sorted(no_device):
        print(f"  {title:28} {key:20} {ctype}")

    # Not a failure, and not a pass either. A Brain push of one of these lands on
    # `glassEventCard`, which draws `eyebrow` and `primary` only — fine for a
    # card whose whole content is those two fields, wrong for one whose answer
    # lives elsewhere. Printed so the judgement is made per card by a human
    # rather than absorbed into a green line.
    print(f"\ngeneric on the Live Lens ({len(gutted)}) — produced and drawn on "
          f"the device, but the Brain's own surface falls back to eyebrow+primary")
    for title, key, builder, ctype, made in sorted(gutted):
        print(f"  {title:28} {ctype}")

    print(f"\ndrawn properly on both surfaces ({len(ok)})")
    for title, key, builder, ctype, made in sorted(ok):
        via = ("   via " + ", ".join(sorted(m.replace(PKG + ".", "")
                                            for m in made)[:3])) if args.verbose else ""
        print(f"  {title:28} {ctype}{via}")

    # Cards the Brain can push that the demo catalog never declares. Reported
    # last because they are the ones no other bucket can see, and unreachability
    # here is measured the same way: does either surface name the type?
    declared_types = {types.get(samples.get(k, ""), "") for _f, _t, k in features}
    inline = {t: m for t, m in _inline_card_types(reachable).items()
              if t not in declared_types}
    pushed, unresolved = _pushed_types(reachable)
    print(f"\nUNDECLARED ({len(inline)}) — built by the Brain, absent from "
          f"demo/catalog.py, so no bucket above counts them")
    for ctype, made in sorted(inline.items()):
        via = ("   via " + ", ".join(sorted(m.replace(PKG + ".", "")
                                            for m in made)[:2])) if args.verbose else ""
        if ctype not in pushed and ctype not in _BRAIN_ONLY_PUSHED:
            print(f"  {ctype:24} not observed pushed — JSON only, so never "
                  f"generic{via}")
            continue
        where = [n for n, s in (("device", device), ("live lens", live)) if ctype in s]
        print(f"  {ctype:24} PUSHED · drawn on: "
              f"{', '.join(where) or 'NEITHER — generic only'}{via}")
    if unresolved:
        # Printed, never swallowed: each of these is a real push whose card type
        # this script could not name, so "not observed pushed" above means only
        # that — not that the card stays off the glass.
        print(f"  ({len(unresolved)} push site(s) with an unresolvable card "
              f"expression: {', '.join(sorted(unresolved))})")

    # An undeclared card that is PUSHED and drawn nowhere is the same defect
    # class as a declared card with no renderer, so it fails the same way. One
    # that is only ever returned as JSON is not a defect at all.
    orphan = [t for t in inline
              if (t in pushed or t in _BRAIN_ONLY_PUSHED)
              and t not in device and t not in live]
    return 1 if (no_producer or no_device or orphan) else 0


if __name__ == "__main__":
    sys.exit(main())
