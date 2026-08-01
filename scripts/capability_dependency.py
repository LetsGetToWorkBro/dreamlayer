#!/usr/bin/env python3
"""Does installing the declared dependency change anything?

`capabilities.py` declares, for every capability, the pip modules its meter
probes (`Cap.modules` — "any-of import names, EXACTLY as the adapter imports
them"). The three `*_reachability.py` checkers ask whether the Brain can reach
a capability's seam. None asks the question one level up: the seam imports the
declared module — but does any code path actually USE it, or is the import only
there to make the meter move?

It is not always used. `structured_output` declared `("outlines", "instructor")`
and `reality_compiler/intent_parser_llm.py` imported both purely as availability
probes (`# noqa: F401`) and called neither — and `parse()` *gated* on them, so a
wearer who had wired a local model got the bare regex parser until they
installed two libraries that did nothing (#575 ungated it; the probes remain).
A grep for the same shape finds `typed_pipeline` (`pydantic_ai`, probe only —
the sequential fallback is the only implementation) and `persona_tuning`
(`hulearn`, probe only — the rule is injected, never built from hulearn).

Three buckets:

  * USED — the seam references the module, or a symbol imported from it, in
    code. `from X import Y` then calling `Y` is real use: the binding is
    resolved through the AST (`ImportFrom` → `alias.asname or alias.name`), not
    grepped, so a mention inside a comment or docstring does NOT count — which
    is exactly the case a regex gets wrong and `ast` gets right for free.
  * PROBE WITH A REAL PATH ELSEWHERE — the module is only a probe in the seam,
    but something the seam CALLS genuinely uses it. `pii_redaction` is the
    worked example and the case this checker must not flag: `pii_presidio.py`
    imports `presidio_analyzer` as a bare probe and builds the engine through
    `nlp_setup.analyzer_engine()`, which imports `AnalyzerEngine` from
    `presidio_analyzer` and calls it. Flagging that is crying wolf on correct
    code, so the report follows the seam's OWN in-package imports (only the
    ones its code actually references) until it finds the real use.
  * PROBE ONLY — nothing anywhere uses it. Installing the extra moves the
    meter and changes no behaviour. This is the list to read.

READ THE OUTPUT AS TRIAGE, NOT A SCORE, like its siblings — and like
`capability_reachability.py` it exits 0, because "this dependency is dead
weight" has a legitimate reading (a declared-but-unwired path, tracked as its
own issue) that "a declared lens cannot be loaded" does not.

    $ python3 scripts/capability_dependency.py
    $ python3 scripts/capability_dependency.py --verbose   # show the USED bucket too
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PKG = "dreamlayer"
SRC = ROOT / "host-python" / "src" / PKG


def _cap_module():
    """Reuse the sibling's Cap catalogue and seam-string parser — one reader
    of `capabilities.py`'s shape, not two."""
    spec = importlib.util.spec_from_file_location(
        "_cap_reachability", HERE / "capability_reachability.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _declared_caps() -> list[tuple[str, str, tuple[str, ...], str]]:
    """(key, title, modules, seam) for every `Cap(...)`.

    `modules` is the 4th positional argument (a tuple of import names) and
    `seam` the 6th; keyword forms are read too, the same courtesy the sibling
    extends to `seam`, so a later edit does not silently drop an entry out of
    the audit. `kind="service"` capabilities declare an EMPTY tuple — nothing
    is pip-installed for them, so there is no probe to audit; they are returned
    with `()` and classify() simply finds no rows for them.
    """
    tree = ast.parse((SRC / "capabilities.py").read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Cap"):
            continue
        args = [a.value if isinstance(a, ast.Constant) else None for a in node.args]
        key, title = (args + [None, None])[:2]
        modules: tuple[str, ...] | None = None
        seam = args[5] if len(args) >= 6 else None
        if len(args) >= 4 and isinstance(node.args[3], ast.Tuple):
            elts = [e.value for e in node.args[3].elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            modules = tuple(elts)
        for kw in node.keywords:
            if kw.arg == "modules" and isinstance(kw.value, ast.Tuple):
                modules = tuple(e.value for e in kw.value.elts
                                if isinstance(e, ast.Constant)
                                and isinstance(e.value, str))
            if kw.arg == "seam" and isinstance(kw.value, ast.Constant):
                seam = kw.value.value
        if key and modules is not None:
            out.append((key, title or "", modules, seam or ""))
    return out


def _package_modules(src: pathlib.Path = SRC) -> dict[str, pathlib.Path]:
    """Every module in the package, dotted name → path.

    Tests are excluded: a test importing the declared module is not a code path
    the product can take — the same rule the sibling applies to `DL_WIRED_*`
    flags ("a test setting a flag proves nothing").
    """
    out = {}
    for path in src.rglob("*.py"):
        if "/tests/" in path.as_posix():
            continue
        rel = path.relative_to(src).with_suffix("")
        parts = [p for p in rel.parts if p != "__init__"]
        out[".".join([PKG, *parts])] = path
    return out


def _tree(path: pathlib.Path, cache: dict) -> ast.Module | None:
    if path not in cache:
        try:
            cache[path] = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, OSError, ValueError):
            cache[path] = None
    return cache[path]


def _bound_names(tree: ast.Module, module: str) -> set[str]:
    """Names this file binds FROM `module` (or any submodule of it).

    `import presidio_analyzer` binds `presidio_analyzer`; `from presidio_analyzer
    import AnalyzerEngine as AE` binds `AE`. The binding — not the module name —
    is what later code can reference, which is the whole reason this is an AST
    walk and not a grep.
    """
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == module or a.name.startswith(module + "."):
                    out.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == module or mod.startswith(module + "."):
                for a in node.names:
                    out.add(a.asname or a.name)
    return out


def _loaded_names(tree: ast.Module) -> set[str]:
    """Names actually loaded in code. Comments and docstrings produce no
    `ast.Name` nodes, so a module mentioned only in prose is not used — the
    property a regex cannot give you."""
    return {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _used_symbols(tree: ast.Module, module: str) -> set[str]:
    """The bindings from `module` this file references in code (may be empty —
    the empty case IS the probe this checker exists to catch)."""
    return _bound_names(tree, module) & _loaded_names(tree)


def _pkg_imports(dotted: str, tree: ast.Module) -> dict[str, str]:
    """{bound_name: absolute in-package module} this file imports — both
    relative (`from .. import nlp_setup`) and absolute (`from dreamlayer.x
    import y`) forms, resolved against the importing module's own package."""
    pkg_of = dotted.split(".")[:-1]
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == PKG or a.name.startswith(PKG + "."):
                    out[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_of[:len(pkg_of) - (node.level - 1)]
                if node.module:
                    base = base + node.module.split(".")
                for a in node.names:
                    # `from ..x import y` binds y FROM module x; `from .. import
                    # x` binds the submodule x itself.
                    out[a.asname or a.name] = ".".join(base) if node.module \
                        else ".".join([*base, a.name])
            elif node.module and (node.module == PKG
                                  or node.module.startswith(PKG + ".")):
                for a in node.names:
                    out[a.asname or a.name] = node.module
    return out


def _real_path_elsewhere(module: str, seam_mod: str, by_mod: dict,
                         cache: dict) -> str:
    """The dotted name of a module the seam CALLS that genuinely uses `module`,
    or "".

    Walks the seam's own in-package imports — only ones the seam's code
    actually references, because an unused import is another probe, not a call —
    then theirs, until some module in that closure uses `module`. This is the
    `pii_redaction` case: the seam probes `presidio_analyzer` and calls
    `nlp_setup.analyzer_engine()`; `nlp_setup` is where `AnalyzerEngine` is
    really imported and called. Without this hop the checker flags correct code,
    and a checker that cries wolf gets ignored, which is worse than not having
    one.
    """
    seen = {seam_mod}
    frontier = [seam_mod]
    while frontier:
        current = frontier.pop()
        tree = _tree(by_mod[current], cache) if current in by_mod else None
        if tree is None:
            continue
        loaded = _loaded_names(tree)
        for bound, target in _pkg_imports(current, tree).items():
            if bound not in loaded or target in seen or target not in by_mod:
                continue
            seen.add(target)
            target_tree = _tree(by_mod[target], cache)
            if target_tree is not None and _used_symbols(target_tree, module):
                return target
            frontier.append(target)
    return ""


def _classify_module(module: str, seam_mods: list[str], by_mod: dict,
                     cache: dict) -> tuple[str, str]:
    """(bucket, evidence) for one declared module against one capability's seams.

    bucket is "used" | "indirect" | "probe". Split out of `classify` so the
    verdict can be asserted on directly — a checker whose conclusions live only
    in stdout is the least testable shape it could take.
    """
    for mod in seam_mods:
        tree = _tree(by_mod[mod], cache) if mod in by_mod else None
        if tree is None:
            continue
        symbols = _used_symbols(tree, module)
        if symbols:
            return ("used", f"{mod} imports and references "
                    f"{', '.join(sorted(symbols))}")
    for mod in seam_mods:
        if mod not in by_mod:
            continue
        hit = _real_path_elsewhere(module, mod, by_mod, cache)
        if hit:
            return ("indirect", f"only a probe in {mod}, but {hit} — which "
                    f"the seam calls — imports and uses it")
    return ("probe", "imported for the meter and referenced by no code path")


def classify(by_mod: dict | None = None) -> dict:
    """Sort every declared `Cap.modules` entry into its bucket. The whole verdict."""
    cap = _cap_module()
    if by_mod is None:
        by_mod = _package_modules()
    cache: dict = {}
    used, indirect, probe, no_seam = [], [], [], []
    for key, _title, modules, seam in _declared_caps():
        seam_mods = cap._seam_modules(seam)
        for module in modules:
            if not seam_mods:
                no_seam.append((key, module, seam, "no adapter file named"))
                continue
            bucket, why = _classify_module(module, seam_mods, by_mod, cache)
            row = (key, module, seam, why)
            {"used": used, "indirect": indirect,
             "probe": probe}[bucket].append(row)
    return {"used": used, "indirect": indirect, "probe": probe,
            "no_seam": no_seam}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true",
                    help="also list the dependencies that ARE used in their seam")
    args = ap.parse_args()

    b = classify()
    used, indirect, probe, no_seam = (b["used"], b["indirect"],
                                      b["probe"], b["no_seam"])
    total = len(used) + len(indirect) + len(probe) + len(no_seam)

    print(f"{total} declared dependency modules · {len(used)} used · "
          f"{len(indirect)} used through a real path elsewhere · "
          f"{len(probe)} probe-only")

    print(f"\nPROBE ONLY ({len(probe)}) — installing the extra moves the meter "
          f"and changes no behaviour")
    print("  The seam imports the module as an availability probe (`noqa: F401`)\n"
          "  and no code path — in the seam, or in anything the seam calls —\n"
          "  references it. `structured_output` was the first of these: two\n"
          "  libraries a wearer installed for nothing, and a gate that punished\n"
          "  them for not. This is the list to read.\n"
          "  One reading is honest, not dead weight: `Cap.modules` is ANY-OF, so\n"
          "  an entry here whose sibling IS used (`vector_search` probes chroma/\n"
          "  lance/sqlite_vec and runs on usearch) is the meter probing\n"
          "  alternatives. The entries with no used sibling have no such excuse.")
    for key, module, seam, why in sorted(probe):
        print(f"  {key:24} {module:20} {seam}")

    print(f"\nPROBE WITH A REAL PATH ELSEWHERE ({len(indirect)}) — the probe is "
          f"honest, the use is one call away")
    print("  Only a probe IN the seam, but something the seam calls imports and\n"
          "  uses the module — `pii_redaction` probes `presidio_analyzer` and\n"
          "  builds its engine through `nlp_setup.analyzer_engine()`. Flagging\n"
          "  these would be crying wolf on correct code.")
    for key, module, seam, why in sorted(indirect):
        print(f"  {key:24} {module:20} {seam}\n      {why}")

    if no_seam:
        print(f"\nno adapter file ({len(no_seam)}) — a documented recipe, not "
              f"a seam")
        for key, module, seam, why in sorted(no_seam):
            print(f"  {key:24} {module:20} {why}")

    if args.verbose:
        print(f"\nUSED ({len(used)}) — the seam itself references the module")
        for key, module, seam, why in sorted(used):
            print(f"  {key:24} {module:20} {seam}\n      {why}")

    # Deliberately 0, for the same reason `capability_reachability.py` exits 0:
    # probe-only entries are triage with their own tracking issues, not a gate
    # with no legitimate reading. A number to argue with beats a gate that
    # fails for a good reason.
    return 0


if __name__ == "__main__":
    sys.exit(main())
