#!/usr/bin/env python3
"""Which declared capabilities can the shipped Brain actually reach?

`capabilities.py` declares 74 capabilities and a meter that reports each as
installed / active / dormant. Every one names a `seam` — "the adapter file that
consumes it", in the dataclass's own words. That field is what makes this
checkable: a capability whose seam is outside the Brain's import closure cannot
be exercised by the shipped product no matter what the meter says, because no
code path can load the file that would use it.

This is the third checker of the same shape, after `lens_reachability.py` and
`hud_reachability.py`, and it exists for the same reason: the meter is
self-reported. `installed()` asks whether a *module imports*, which answers "is
the library on disk", not "does anything here use it". Those came apart badly
once already — `ear.py` used to promote a batch of voice capabilities to
"active" on start, describing engines that were not running, and now promotes
only the ones a run genuinely drives.

READ THE OUTPUT AS TRIAGE, NOT A SCORE. Unlike lenses, a great many of these
SHOULD be unreachable from the Brain and making them reachable would be a
regression:

  * `orchestrator/*` seams — the shipped Brain never builds an `Orchestrator`
    (`decisions/0001`). Wiring them is the resurrection three PRs exist to
    prevent.
  * other targets — `simulator/*`, `bridge/frame_sdk.py`, `rem/nightly_mlx.py`
    are the desktop stand-in, a different pair of glasses, and a Mac-only
    nightly job.

So this prints the list and the reason bucket, and — unlike its two siblings —
exits 0. A number to argue with beats a gate that fails for a good reason.

The one thing an entry here always means: **if you believe a capability is live
in the shipped product and it appears below, one of the two is wrong.** Either
the seam string is stale (it names a file the Brain replaced — `vector_search`
points at `memory/vector_store.py` while the Brain uses `memory/ann_index.py`)
or the capability genuinely is not wired. Both are worth knowing; they need
opposite fixes.

    $ python3 scripts/capability_reachability.py
    $ python3 scripts/capability_reachability.py --verbose   # show reachable too
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

# Seams that are unreachable ON PURPOSE, with the reason. Anything not matched
# here and not in the closure is an open question, which is the list worth
# reading.
_BY_DESIGN = (
    ("orchestrator/", "Orchestrator-only — the Brain never builds one (decisions/0001)"),
    ("simulator/", "the desktop simulator, not the product"),
    ("bridge/", "a different device's SDK"),
    ("rem/", "the nightly REM job; the Brain runs no REM"),
)


def _lens_module():
    """Reuse the import-closure walker — one graph builder, not three."""
    spec = importlib.util.spec_from_file_location(
        "_lens_reachability", HERE / "lens_reachability.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _declared_caps() -> list[tuple[str, str, str, str]]:
    """(key, title, tier, seam) for every `Cap(...)`.

    `seam` is the 6th positional argument — all 74 pass it positionally today,
    and a keyword form is read too so a later edit does not silently drop an
    entry out of the audit.
    """
    tree = ast.parse((SRC / "capabilities.py").read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Cap"):
            continue
        args = [a.value if isinstance(a, ast.Constant) else None for a in node.args]
        seam = args[5] if len(args) >= 6 else None
        for kw in node.keywords:
            if kw.arg == "seam" and isinstance(kw.value, ast.Constant):
                seam = kw.value.value
        if len(args) >= 3:
            out.append((args[0], args[1], args[2], seam or ""))
    return out


def _seam_modules(seam: str) -> list[str]:
    """Module names named by a seam string.

    Seams are prose with paths in them — "memory/vector_store.py (+chroma/lance
    /usearch siblings)", "orchestrator/commitment_nlp.py, social_lens/ner_spacy.py"
    — so every `*.py` path is extracted and ANY of them being reachable counts.
    A seam with no path at all ("docs (SYNCTHING.md recipe)") is a concept, not
    an adapter, and is reported separately rather than as a failure.
    """
    return [f"{PKG}." + m[:-3].replace("/", ".")
            for m in re.findall(r"[\w/]+\.py", seam or "")]


def _by_design(seam: str) -> str:
    for prefix, why in _BY_DESIGN:
        if prefix in (seam or ""):
            return why
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true",
                    help="also list the capabilities whose seam IS reachable")
    args = ap.parse_args()

    lens = _lens_module()
    files = lens._sources()
    known = {lens._module_name(p) for p in files}
    _roots, reachable = lens._closure(lens._import_graph(files), known)

    caps = _declared_caps()
    open_gaps, expected, concepts, ok = [], [], [], []
    for key, title, tier, seam in caps:
        mods = _seam_modules(seam)
        if not mods:
            concepts.append((key, tier, seam))
        elif any(m in reachable for m in mods):
            ok.append((key, tier, seam))
        elif _by_design(seam):
            expected.append((key, tier, seam, _by_design(seam)))
        else:
            open_gaps.append((key, tier, seam))

    print(f"{len(caps)} declared capabilities · {len(ok)} with a seam the Brain "
          f"can load")

    print(f"\nOPEN — seam not in the Brain's closure and no reason on file "
          f"({len(open_gaps)})")
    print("  Either the seam string is stale (it names a file the Brain "
          "replaced) or\n  the capability is not wired. Opposite fixes; both "
          "worth knowing.")
    for key, tier, seam in sorted(open_gaps):
        print(f"  {key:24} {tier:12} {seam}")

    print(f"\nunreachable BY DESIGN ({len(expected)}) — reaching these would be "
          f"the regression")
    for key, tier, seam, why in sorted(expected):
        print(f"  {key:24} {tier:12} {why}")

    if concepts:
        print(f"\nno adapter file ({len(concepts)}) — a documented recipe, not "
              f"a seam")
        for key, tier, seam in sorted(concepts):
            print(f"  {key:24} {tier:12} {seam}")

    if args.verbose:
        print(f"\nseam reachable ({len(ok)})")
        for key, tier, seam in sorted(ok):
            print(f"  {key:24} {tier:12} {seam}")

    # Deliberately 0: this is a diagnostic to argue with, not a gate. Its two
    # siblings fail the build because "a declared lens cannot be loaded" and "a
    # promised card cannot be drawn" have no legitimate reading; "this adapter
    # belongs to the Orchestrator" has several.
    return 0


if __name__ == "__main__":
    sys.exit(main())
