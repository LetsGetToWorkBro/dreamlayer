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

Four buckets:

  * USED — the seam references the module, or a symbol imported from it, in
    code. `from X import Y` then calling `Y` is real use: the binding is
    resolved through the AST (`ImportFrom` → `alias.asname or alias.name`), not
    grepped, so a mention inside a comment or docstring does NOT count — which
    is exactly the case a regex gets wrong and `ast` gets right for free.
  * PROBE WITH A REAL PATH ELSEWHERE — the module is only a probe in the seam
    (or not even imported there), but a module the seam's code references
    imports and uses it. `pii_redaction` is the worked example and the case
    this checker must not flag: `pii_presidio.py` imports `presidio_analyzer`
    as a bare probe and builds the engine through
    `nlp_setup.analyzer_engine()`, which imports `AnalyzerEngine` from
    `presidio_analyzer` and calls it. Flagging that is crying wolf on correct
    code, so the report follows the seam's OWN in-package imports (only the
    ones its code actually references) until it finds the real use.
    GRANULARITY: that hop is established at MODULE level — "the seam's code
    references a name bound to in-package module M, and M uses the dep
    somewhere in its code". It is NOT proof that the symbol the seam calls
    is the code that uses the dep. See KNOWN LIMITATIONS below; the two live
    rows were verified at symbol level by hand, the checker cannot promise it.
  * USED ELSEWHERE, OFF THE SEAM'S PATH — the module IS imported and used by
    real code in the package, but no path reachable from the declared seam
    reaches that use. `vector_search` is the case: chromadb / lancedb /
    sqlite_vec back full store implementations (chroma_store.py,
    lance_store.py, vector_store.py) that the declared seam (ann_index.py)
    never reaches — and that nothing in production constructs (the only
    call sites outside tests are the stores' own internal fallbacks;
    docs/INNOVATION_SESSION.md already lists them as "reachable only from
    the test suite"). Not a dead dependency — a dead wiring, and arguably
    the more useful finding. Calling these "probe only" was wrong: their
    code is real, only the declaration's pointer is.
  * PROBE ONLY — nothing anywhere in the package uses it (that is now true
    by construction: anything used elsewhere landed in the bucket above).
    The dependency itself is dead weight. NOTE what this bucket does NOT
    establish: "installing the extra changes no behaviour". Most seams gate
    on the probe, so installing can flip behaviour that still owes nothing
    to the library — `causal_fusion.assess()` returns a fixed heuristic
    score once dowhy is present, a score computed without dowhy;
    `structured_output` once REFUSED to answer without two libraries it
    never called. Read the gate before concluding.

KNOWN LIMITATIONS (pinned by TestKnownLimitationsModuleGranularity — those
tests assert the CURRENT, limited behaviour so a future fix must retire
them deliberately, not silently):

  * Module granularity, not symbol level. If the seam calls only
    `helper.foo()` and the dep is used only in `helper.bar()` (which
    nothing calls), the checker still reports the indirect bucket.
  * "References" is syntactic. `if False: helper.foo()` counts as the seam
    calling helper — any `ast.Name` load anywhere in the file qualifies.
  * No scope analysis. `from dep import thing` plus `def go(thing): ...`
    reads as USE: every load of `thing` resolves to the parameter, never
    the import, but the checker cannot tell the difference.
  * String forms cut both ways. A use that lives in a string —
    `__all__ = ["thing"]` re-export, `importlib.import_module("dep")` —
    is invisible (counted as no-use). Conversely an annotation under
    `from __future__ import annotations` produces an `ast.Name` load the
    module never executes at runtime; the real-tree rows this touches
    (FastAPI/pydantic resolve those annotations themselves) are correct
    by luck of the framework, not by the checker's reasoning.

What a verdict here does and does not establish: USED and the indirect
bucket mean "the AST shows a reference", subject to the limitations above;
PROBE ONLY means "no reference exists anywhere in the package" — it says
nothing about what installing the package does to a gate.

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
    """The dotted name of a module reachable from the seam's code that
    genuinely uses `module`, or "".

    Walks the seam's own in-package imports — only ones the seam's code
    actually references, because an unused import is another probe, not a call —
    then theirs, until some module in that closure uses `module`. This is the
    `pii_redaction` case: the seam probes `presidio_analyzer` and calls
    `nlp_setup.analyzer_engine()`; `nlp_setup` is where `AnalyzerEngine` is
    really imported and called. Without this hop the checker flags correct code,
    and a checker that cries wolf gets ignored, which is worse than not having
    one.

    GRANULARITY: the hop is MODULE-level. A hit proves "the seam's code
    references a name bound to M, and M uses `module` somewhere" — not that
    the symbol the seam calls is the code using `module`. The three shapes
    that exposes (cross-function use, dead-code references, shadowed
    bindings) are pinned in TestKnownLimitationsModuleGranularity.
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


def _used_elsewhere_off_seam(module: str, by_mod: dict, cache: dict) -> list[str]:
    """Package modules that genuinely import-and-reference `module`.

    Only called after the seam itself and the seam's reachable closure have
    both come up empty, so any hit here is by construction a use the declared
    seam cannot reach — the `vector_search` case (chroma_store.py et al. are
    real code; ann_index.py just never gets there). Tests are excluded from
    `by_mod` already: a test using the dep is not a product code path.
    """
    users = []
    for dotted, path in sorted(by_mod.items()):
        tree = _tree(path, cache)
        if tree is not None and _used_symbols(tree, module):
            users.append(dotted)
    return users


def _classify_module(module: str, seam_mods: list[str], by_mod: dict,
                     cache: dict) -> tuple[str, str]:
    """(bucket, evidence) for one declared module against one capability's seams.

    bucket is "used" | "indirect" | "elsewhere" | "probe". Split out of
    `classify` so the verdict can be asserted on directly — a checker whose
    conclusions live only in stdout is the least testable shape it could take.
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
            tree = _tree(by_mod[mod], cache)
            # "only a probe" claims an import exists; person_guard.py declares
            # presidio_analyzer without importing it AT ALL, and the evidence
            # string must say which of the two is actually there.
            probe = ("only a probe" if tree is not None
                     and _bound_names(tree, module) else "not even imported")
            return ("indirect", f"{probe} in {mod}; {hit} — reachable from "
                    f"the seam's code at module granularity — imports and "
                    f"uses it")
    users = _used_elsewhere_off_seam(module, by_mod, cache)
    if users:
        return ("elsewhere", "no path from the declared seam reaches it, but "
                f"{', '.join(users)} imports and uses it — real code, dead "
                f"wiring")
    return ("probe", "imported for the meter and referenced by no code path "
            "anywhere in the package")


def classify(by_mod: dict | None = None) -> dict:
    """Sort every declared `Cap.modules` entry into its bucket. The whole verdict."""
    cap = _cap_module()
    if by_mod is None:
        by_mod = _package_modules()
    cache: dict = {}
    used: list[tuple[str, str, str, str]] = []
    indirect: list[tuple[str, str, str, str]] = []
    elsewhere: list[tuple[str, str, str, str]] = []
    probe: list[tuple[str, str, str, str]] = []
    no_seam: list[tuple[str, str, str, str]] = []
    for key, _title, modules, seam in _declared_caps():
        seam_mods = cap._seam_modules(seam)
        for module in modules:
            if not seam_mods:
                no_seam.append((key, module, seam, "no adapter file named"))
                continue
            bucket, why = _classify_module(module, seam_mods, by_mod, cache)
            row = (key, module, seam, why)
            {"used": used, "indirect": indirect, "elsewhere": elsewhere,
             "probe": probe}[bucket].append(row)
    return {"used": used, "indirect": indirect, "elsewhere": elsewhere,
            "probe": probe, "no_seam": no_seam}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true",
                    help="also list the dependencies that ARE used in their seam")
    args = ap.parse_args()

    b = classify()
    used, indirect, elsewhere, probe, no_seam = (
        b["used"], b["indirect"], b["elsewhere"], b["probe"], b["no_seam"])
    total = (len(used) + len(indirect) + len(elsewhere) + len(probe)
             + len(no_seam))

    print(f"{total} declared dependency modules · {len(used)} used · "
          f"{len(indirect)} used through a real path elsewhere · "
          f"{len(elsewhere)} used off the seam's path · "
          f"{len(probe)} probe-only")

    print(f"\nPROBE ONLY ({len(probe)}) — nothing anywhere in the package "
          f"references the declared module")
    print("  The seam imports the module as an availability probe (`noqa: F401`)\n"
          "  or never imports it at all, and no code path — in the seam, in\n"
          "  anything the seam's code reaches, or anywhere else in the package —\n"
          "  references it. The DEPENDENCY is dead weight. What this list does\n"
          "  NOT prove is 'installing it changes no behaviour': most of these\n"
          "  seams gate on the probe, so installing flips behaviour that still\n"
          "  owes nothing to the library — `causal_fusion.assess()` answers\n"
          "  with a fixed heuristic once dowhy is present (a score computed\n"
          "  without dowhy), and `structured_output` once REFUSED to answer\n"
          "  without two libraries it never called. Read the gate, not just\n"
          "  the meter. Some entries are already-admitted dormancy, not new\n"
          "  discoveries: coreml_ondevice (docs/AUDIT_2026-07-14.md calls the\n"
          "  backend a dead placeholder; capabilities.py declares it unwired)\n"
          "  and the facial_aus trio (docs/INTEGRATIONS.md: 'AU frame passed\n"
          "  through untouched').")
    for key, module, seam, _why in sorted(probe):
        print(f"  {key:24} {module:20} {seam}")

    print(f"\nUSED ELSEWHERE, OFF THE SEAM'S PATH ({len(elsewhere)}) — real "
          f"code uses it; the declared seam never gets there")
    print("  The module IS imported and used by real code in the package, so\n"
          "  'probe only — nothing anywhere uses it' would be demonstrably\n"
          "  false; but no path reachable from the declared seam reaches that\n"
          "  use, so the declaration is still dishonest about what installing\n"
          "  it buys. `vector_search` is the case: chromadb / lancedb /\n"
          "  sqlite_vec back full store implementations (chroma_store.py,\n"
          "  lance_store.py, vector_store.py) that nothing in production\n"
          "  constructs — the only call sites outside tests are the stores'\n"
          "  own internal fallbacks, and docs/INNOVATION_SESSION.md already\n"
          "  lists them as 'reachable only from the test suite'. Not a dead\n"
          "  dependency — a dead wiring, and arguably the more useful finding.")
    for key, module, seam, why in sorted(elsewhere):
        print(f"  {key:24} {module:20} {seam}\n      {why}")

    print(f"\nPROBE WITH A REAL PATH ELSEWHERE ({len(indirect)}) — the probe is "
          f"honest, the use is one call away")
    print("  Only a probe in the seam (or not even an import there), but a\n"
          "  module the seam's code references imports and uses the dep —\n"
          "  `pii_redaction` probes `presidio_analyzer` and builds its engine\n"
          "  through `nlp_setup.analyzer_engine()`. Flagging these would be\n"
          "  crying wolf on correct code. GRANULARITY CAVEAT: reachability\n"
          "  here is module-level — 'the seam calls somewhere into M, and M\n"
          "  uses the dep somewhere' — NOT proof the symbol the seam calls is\n"
          "  the code using the dep. Both rows below were verified at symbol\n"
          "  level by hand; the checker alone cannot promise that (see KNOWN\n"
          "  LIMITATIONS in the docstring).")
    for key, module, seam, why in sorted(indirect):
        print(f"  {key:24} {module:20} {seam}\n      {why}")

    if no_seam:
        print(f"\nno adapter file ({len(no_seam)}) — a documented recipe, not "
              f"a seam")
        for key, module, _seam, why in sorted(no_seam):
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
