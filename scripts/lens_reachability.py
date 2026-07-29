#!/usr/bin/env python3
"""Which declared lenses can the shipped Brain actually reach?

`lenses.py` declares the product's lenses. The shipped Brain is `ai_brain/`;
it never constructs an `Orchestrator` (see `decisions/0001`), so a lens that
lives only on the Orchestrator is invisible from the phone no matter how
complete its implementation is. That has been true of retention, of the Social
Lens, and — this script exists because nobody had checked the rest — of a dozen
more.

Grep cannot answer this. `quest` matches "request", `provenance` matches a
schema field and two comments, and a docstring naming `lucid_recall` is not an
import. So this walks the real import graph:

  * every .py in the package is AST-parsed, INCLUDING function-level imports
    (this codebase lazy-imports almost everything, so a module-header-only scan
    would miss most edges);
  * relative imports are resolved properly, which is fiddly enough to get wrong
    twice — `from ...orchestrator.taste import X` inside
    `ai_brain/server/world_lens.py` is `dreamlayer.orchestrator.taste`, and the
    arithmetic differs for a package `__init__.py`;
  * BFS from every `dreamlayer.ai_brain.*` module;
  * a lens counts as reachable if ITS module or any DESCENDANT is in the
    closure, because importing `dreamlayer.social_lens.index` also runs the
    package `__init__`.

WHAT THIS PROVES, AND WHAT IT DOES NOT. Not-in-the-closure is a hard NO: no code
path from the Brain can even load it. In-the-closure is an UPPER BOUND, not a
pass — `RetentionSweep` was importable for years while never being called, which
is the whole of decision 0001. Reachability can also flatter at package level: a
lens counts as reachable when one submodule is wired even if the part that
matters is not (`truth_lens` is reachable only via the face embedder; the
credibility analyzer is not reached by anything).

    $ python3 scripts/lens_reachability.py
    $ python3 scripts/lens_reachability.py --verbose     # show what reached each
"""
from __future__ import annotations

import argparse
import ast
import collections
import pathlib
import sys

PKG = "dreamlayer"
SRC = pathlib.Path(__file__).resolve().parents[1] / "host-python" / "src" / PKG


def _module_name(path: pathlib.Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([PKG] + parts)


def _sources() -> list[pathlib.Path]:
    return [p for p in SRC.rglob("*.py")
            if "tests" not in p.parts and "__pycache__" not in p.parts]


def _import_graph(files):
    edges: dict[str, set[str]] = collections.defaultdict(set)
    for path in files:
        me = _module_name(path)
        is_init = path.name == "__init__.py"
        mine = me.split(".")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                      # not our problem here
            continue
        for node in ast.walk(tree):              # walk: function-level too
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(PKG):
                        edges[me].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    # a module's package is its parent; a package IS itself
                    cut = len(mine) - node.level + (1 if is_init else 0)
                    base = mine[:max(cut, 1)]
                    target = ".".join(base + ([node.module] if node.module else []))
                elif node.module and node.module.startswith(PKG):
                    target = node.module
                else:
                    continue
                edges[me].add(target)
                for alias in node.names:         # `from x import y` may name a module
                    edges[me].add(f"{target}.{alias.name}")
    return edges


def _closure(edges, known):
    def resolve(mod: str) -> str:
        while mod and mod not in known:
            mod = mod.rsplit(".", 1)[0] if "." in mod else ""
        return mod

    roots = sorted(m for m in known if m.startswith(f"{PKG}.ai_brain"))
    seen: set[str] = set()
    queue = list(roots)
    while queue:
        mod = queue.pop()
        if mod in seen:
            continue
        seen.add(mod)
        for target in edges.get(mod, ()):
            nxt = resolve(target)
            if nxt and nxt not in seen:
                queue.append(nxt)
    return roots, seen


def _declared_lenses():
    tree = ast.parse((SRC / "lenses.py").read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Feature":
            args = [ast.literal_eval(a) if isinstance(a, ast.Constant) else None
                    for a in node.args]
            if len(args) >= 2:
                out.append((args[0], args[1], args[-1]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true",
                    help="list the modules that made each lens reachable")
    args = ap.parse_args()

    files = _sources()
    known = {_module_name(p) for p in files}
    roots, reached = _closure(_import_graph(files), known)

    print(f"{len(files)} modules · {len(roots)} ai_brain roots · "
          f"{len(reached)} reachable from the Brain")

    unreachable, reachable, lua = [], [], []
    for key, title, module in _declared_lenses():
        if not module or not module.startswith(PKG):
            lua.append((key, title, module))
            continue
        hits = sorted(m for m in reached
                      if m == module or m.startswith(module + "."))
        (reachable if hits else unreachable).append((key, title, module, hits))

    print(f"\nUNREACHABLE from the Brain ({len(unreachable)}) — a hard no: "
          f"no code path can even load these")
    for key, title, module, _ in sorted(unreachable):
        print(f"  {title:20} {module}")

    print(f"\nreachable ({len(reachable)}) — an UPPER BOUND, not proof it runs")
    for key, title, module, hits in sorted(reachable):
        via = f"   via {', '.join(h.replace(PKG + '.', '') for h in hits[:3])}" \
            if args.verbose else ""
        print(f"  {title:20} {module}{via}")

    if lua:
        print(f"\nnot Python ({len(lua)}) — on-glass display effects")
        for key, title, module in sorted(lua):
            print(f"  {title:20} {module}")

    return 1 if unreachable else 0


if __name__ == "__main__":
    sys.exit(main())
