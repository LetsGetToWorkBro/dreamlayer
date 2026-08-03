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

READ THE OUTPUT AS TRIAGE, NOT A SCORE — but read the reasons harder than the
counts, because the reasons are where this drifted.

"Unreachable BY DESIGN" used to hold eleven capabilities and it was a PATH RULE:
anything under `orchestrator/` matched, on the argument that the shipped Brain
never builds an `Orchestrator` (`decisions/0001`) so wiring it would be the
resurrection three PRs exist to prevent. That confuses two different claims.
The Orchestrator must not come back — but "its only consumer is the
Orchestrator" describes where a seam is wired TODAY, and it is precisely the
diagnosis under eight capabilities re-hosted Brain-side during 2026-08-02. The
prefix was filing open work as a settled decision.

So the bucket is split. `_BY_DESIGN` now holds only what is genuinely not a
wearer feature (the desktop simulator), and `_NOT_YET_HOSTED` carries the rest
with the user-facing loss spelled out per key. A key leaves that dict by being
BUILT, never by being reclassified.

This prints the list and the reason bucket, and — unlike its two siblings —
exits 0. A number to argue with beats a gate that fails for a good reason.

Seven buckets, and two of them are defects:

  * UNCONSTRUCTED — the seam IS loadable and nothing outside it names anything
    it defines. The capability-level version of the mistake this whole family of
    checkers is about: an earlier version of this script counted these in the
    good column, because "in the import closure" answers *can this file load*,
    not *does anything use it*. `ai_brain/exo_cluster.py` was the case that
    proved it — importable, in the closure, and `ExoClusterBackend` constructed
    by nothing but a test.
  * MISREPORTED — a seam the Brain cannot load, on a capability that is NOT in
    `capabilities.py:_NOT_WIRED`. The meter will light it green once its pip
    extras install, and nothing can exercise it. **This is the list to read**,
    and it is empty today.
  * DRIVEN, dormant only by default — importable, `_NOT_WIRED` names it, AND a
    live Brain path sets `DL_WIRED_<KEY>` while it genuinely runs. The ear's
    capabilities go active the moment the microphone opens. Not a gap.
  * loadable and dormant with NOTHING promoting it — importable, and no live path
    ever reports it working. Not a false green (the wearer is told dormant) but
    real work, and the shortlist for it. These two started as one bucket with the
    difference written in a comment; a checker should compute a distinction that
    load-bearing, not describe it.
  * declared DORMANT — unreachable and `_NOT_WIRED` says so, so the wearer is
    told "dormant" rather than shown a false green. Honest; still real work.
  * NOT YET HOSTED BRAIN-SIDE — a complete seam whose only consumer is the
    Orchestrator. Real work with a real loss, named in `_NOT_YET_HOSTED`.
  * unreachable BY DESIGN — reaching it would be the regression.

The bucket order matters and it used to be wrong. Loadability was tested FIRST,
so a seam that was both importable and named in `_NOT_WIRED` never reached the
dormant branch — eleven capabilities sat in the good column while the product's
own honesty list said they were unwired. The headline count fell from 42 to 30
when that was fixed, and 30 is the number that means something.

An earlier version had no dormant bucket and printed eighteen `_NOT_WIRED`
capabilities as "no reason on file", when the reason was written out in prose
directly above their names. It buried the single entry that was genuinely
wrong: `vector_search` named `memory/vector_store.py` while the Brain's recall
paths construct `PersistentAnnIndex` from `memory/ann_index.py`. A checker that
reports eighteen non-problems alongside one real one gets read as noise.

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
# Seams that are unreachable ON PURPOSE — and the bar for being here is now
# EVIDENCE ABOUT THE FEATURE, not the directory the file happens to sit in.
#
# This used to be a blanket path rule, and `orchestrator/` swept eight entries
# into it. That was wrong in the way `decisions/0007` warns about from the other
# direction: *"do not shrink this list by moving entries to `_BY_DESIGN` without
# evidence … filing them there would turn a measurement into a claim."* Nobody
# moved them; the prefix did. And "Orchestrator-only" is precisely the reason
# SEVEN capabilities were re-hosted Brain-side during 2026-08-02 — it describes
# where a seam is wired today, never whether it could be reached.
#
# `simulator/` survives because a debug visualiser for developers is genuinely
# not a wearer feature. `bridge/` is gone: the Brain reaches the bridge now
# (`halo_link.py`), and the one entry that used it — `frame_glasses`, for a
# different manufacturer's device — was deleted rather than excused. `rem/` is
# gone too: the nightly job is a SCHEDULER question, and the Brain already runs
# schedulers (`start_retention_scheduler`), so calling it unreachable was the
# same mislabel.
_BY_DESIGN = (
    ("simulator/", "the desktop simulator, not the product"),
)

# …and the entries that are simply NOT BUILT YET, which the report must not
# call "by design". Each is real work with a real user-facing loss, listed here
# so the number is visible instead of hidden inside a bucket that reads as
# settled. Removing a key from here means it got built, never that it got
# reclassified.
_NOT_YET_HOSTED = {
    # `nlp` was the first one out — `ai_brain/server/nlp_live.py` sharpens the
    # `person` and `due` the tier-1 regex leaves empty, on the ingest path every
    # spoken line already takes.
    "onnx_speech": "one on-device engine for ASR + VAD + speaker + wake",
    "wake_word": "\"Hey Juno\" only works because ASR transcribes everything first",
    "home_hud": "the glass never taps you that the garage is open",
    # `lan_discovery` left next — `ai_brain/server/discovery_live.py` advertises
    # the Brain on start and the CLI browses for it when no `--brain` is given.
    "mesh_range": "the tincan bond stays Bluetooth-range instead of miles",
    "fs_watch": "sources rescan on a timer instead of reacting",
    "structured_concurrency": "Veil-stop is hand-rolled rather than structural",
    "mlx_train": "the local model never adapts to the wearer overnight",
}


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


def _not_yet(key: str) -> str:
    """Why this one is unreached, when the reason is "nobody has built it".

    Kept apart from `_by_design` on purpose. A reader who sees "unreachable by
    design" stops looking; a reader who sees "not yet hosted" has a to-do list.
    Merging the two is how eight real features spent months looking settled.
    """
    return _NOT_YET_HOSTED.get(key, "")


def _declared_dormant() -> set[str]:
    """The keys `capabilities.py` already declares unwired, via `_NOT_WIRED`.

    Without this, the OPEN bucket was materially dishonest: it printed 19
    capabilities under "no reason on file" when 18 of them are named in
    `_NOT_WIRED`, with the reason written out in prose immediately above them
    ("…are NOT promoted — they need the full Orchestrator path"). Those are not
    open questions — the product reports them DORMANT to the wearer, which is
    the correct status for an adapter nothing calls. Conflating them with a
    genuine discrepancy buried the one entry that mattered.

    Read from the AST rather than imported: this script deliberately never
    imports the package it audits (importing `dreamlayer` would execute module
    bodies and could itself pull seams into the closure being measured).
    """
    tree = ast.parse((SRC / "capabilities.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", "") == "_NOT_WIRED" for t in node.targets):
            continue
        # frozenset({...}) — the set literal is the sole call argument
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Set):
                return {e.value for e in sub.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _runtime_promoted() -> set:
    """Keys a LIVE Brain path promotes from dormant to active at runtime.

    `wired_now()` reads `DL_WIRED_<KEY>`, which a subsystem sets only while it is
    genuinely driving the capability. Two mechanisms exist and both are read here,
    because the difference they encode is the one this bucket used to leave to a
    prose comment — "some of these are driven, just conditionally; the rest have no
    live surface at all" is a distinction a checker should COMPUTE, not describe:

      * a promoted-caps tuple (`ear.py:EAR_CAPS`), whose keys the Brain turns into
        flags in a loop, so no literal flag name appears in the source;
      * a literal `DL_WIRED_<KEY>` assignment, for a capability with no start/stop
        event to hang a durable flag on (`social_graph` is computed per report).

    Read from source, never by importing the package — the same rule the rest of
    this script follows.
    """
    keys: set = set()
    ear = SRC / "ai_brain" / "server" / "ear.py"
    try:
        tree = ast.parse(ear.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(getattr(t, "id", "") == "EAR_CAPS" for t in node.targets):
                continue
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    keys.add(sub.value)
    except (SyntaxError, OSError):
        pass
    # literal flags, anywhere in the package
    for path in SRC.rglob("*.py"):
        if "/tests/" in path.as_posix():
            continue                          # a test setting a flag proves nothing
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"DL_WIRED_([A-Z0-9_]+)", text):
            keys.add(m.group(1).lower())
    return keys


def _public_names(path) -> set:
    """Top-level classes/functions a seam module defines, excluding _private."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return set()
    return {n.name for n in tree.body
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and not n.name.startswith("_")}


def _referenced_outside(lens, reachable: set, seam_mods: list) -> bool:
    """Does any OTHER reachable module name something this seam defines?

    The capability-level version of the mistake this whole audit is about. "The
    seam is in the import closure" is the same weak claim `lens_reachability.py`
    warns about in its own header: it says the file CAN be loaded, not that
    anything uses it. `ai_brain/exo_cluster.py` is the case that proves it —
    importable, in the closure, honestly reporting state "external", and
    `ExoClusterBackend` is constructed by nothing, so an exo cluster running on
    the wearer's LAN would never be reached.

    A name match is weaker than a call graph and deliberately so: a false
    "referenced" here means the checker stays quiet, which is the same direction
    the closure test already errs in — this only ever ADDS findings.
    """
    by_mod = {lens._module_name(p): p for p in lens._sources()}
    names: set = set()
    for m in seam_mods:
        if m in by_mod:
            names |= _public_names(by_mod[m])
    if not names:
        return True                          # nothing to reference: not a finding
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b")
    for mod, path in by_mod.items():
        if mod not in reachable or mod in seam_mods:
            continue
        try:
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def classify(lens=None, reachable=None) -> dict:
    """Sort every declared capability into its bucket. The whole verdict.

    Split out of `main` so the buckets can be asserted on directly rather than
    scraped back out of stdout — a checker whose own conclusions are only
    available as printed text is the least testable shape it could take, and
    this one has been wrong about its own conclusions twice.
    """
    if lens is None:
        lens = _lens_module()
    if reachable is None:
        files = lens._sources()
        known = {lens._module_name(p) for p in files}
        _roots, reachable = lens._closure(lens._import_graph(files), known)

    caps = _declared_caps()
    dormant_keys = _declared_dormant()
    promoted_keys = _runtime_promoted()
    open_gaps, dormant, expected, concepts, ok = [], [], [], [], []
    not_yet: list = []
    conditional, unconstructed, driven = [], [], []
    for key, _title, tier, seam in caps:
        mods = _seam_modules(seam)
        live = [m for m in mods if m in reachable]
        if not mods:
            concepts.append((key, tier, seam))
        elif live:
            # LOADABLE is three states, not one, and collapsing them is how this
            # script previously reported 42 capabilities in the good column when
            # eleven of them are named in `_NOT_WIRED` and one is constructed by
            # nothing. The `elif` chain checked loadability FIRST, so a seam that
            # is both importable and declared-not-wired never reached the dormant
            # branch — the importable-never-called trap, in the checker itself.
            #
            # ORDER IS THE CONTRACT HERE: the product's own honesty list wins
            # over loadability, and "does anything name it" wins over "can it
            # load". Reordering these puts capabilities back in the good column.
            if key in dormant_keys:
                # Declared dormant AND loadable splits again, and the split is the
                # difference between "conditionally on" and "inert". A capability a
                # live path PROMOTES at runtime is dormant only as its honest
                # default — the ear's caps go active the moment the microphone
                # opens. One with no promoter is dormant permanently, and reading
                # both from one bucket was how eleven of these looked alike.
                (driven if key in promoted_keys else conditional).append(
                    (key, tier, seam))
            elif not _referenced_outside(lens, reachable, live):
                unconstructed.append((key, tier, seam))
            else:
                ok.append((key, tier, seam))
        elif _not_yet(key):
            not_yet.append((key, tier, seam, _not_yet(key)))
        elif _by_design(seam):
            expected.append((key, tier, seam, _by_design(seam)))
        elif key in dormant_keys:
            dormant.append((key, tier, seam))
        else:
            open_gaps.append((key, tier, seam))

    return {"caps": caps, "ok": ok, "unconstructed": unconstructed,
            "conditional": conditional, "open_gaps": open_gaps,
            "dormant": dormant, "expected": expected, "not_yet": not_yet,
            "concepts": concepts,
            "driven": driven, "promoted_keys": promoted_keys}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true",
                    help="also list the capabilities whose seam IS reachable")
    args = ap.parse_args()

    b = classify()
    caps, ok, unconstructed = b["caps"], b["ok"], b["unconstructed"]
    conditional, open_gaps = b["conditional"], b["open_gaps"]
    dormant, expected, concepts = b["dormant"], b["expected"], b["concepts"]
    not_yet = b["not_yet"]
    driven = b["driven"]

    print(f"{len(caps)} declared capabilities · {len(ok)} with a seam the Brain "
          f"loads AND uses")

    print(f"\nUNCONSTRUCTED ({len(unconstructed)}) — seam loadable, nothing "
          f"names what it defines")
    print("  The capability-level `importable, never called`. In the closure, so\n"
          "  the old report counted these as reachable; no module outside the\n"
          "  seam references anything it defines, so no code path can use it.")
    for key, tier, seam in sorted(unconstructed):
        print(f"  {key:24} {tier:12} {seam}")
    if not unconstructed:
        print("  (none)")

    print(f"\nDRIVEN, dormant only by default ({len(driven)}) — a live path "
          f"promotes these")
    print("  Loadable, declared dormant, and a Brain path sets DL_WIRED_<KEY> while\n"
          "  it genuinely drives them — the ear's caps go active the moment the\n"
          "  microphone opens. `dormant` is the honest DEFAULT here, not a gap. This\n"
          "  used to be a prose caveat on the bucket below; it is computed now.")
    for key, tier, seam in sorted(driven):
        print(f"  {key:24} {tier:12} {seam}")
    if not driven:
        print("  (none)")

    print(f"\nloadable, dormant, and NOTHING promotes them ({len(conditional)})")
    print("  The seam imports and no live path ever reports it working. Not a false\n"
          "  green — the wearer is told dormant — but each is real work, and this is\n"
          "  the shortlist for it.")
    for key, tier, seam in sorted(conditional):
        print(f"  {key:24} {tier:12} {seam}")
    if not conditional:
        print("  (none)")

    print(f"\nMISREPORTED — seam not loadable, and NOT declared dormant "
          f"({len(open_gaps)})")
    print("  The catalog will show these as available once their pip extras are\n"
          "  installed, but no Brain path can load the seam. Either the seam\n"
          "  string is stale (it names a file the Brain replaced) or the key\n"
          "  belongs in `_NOT_WIRED`. Opposite fixes; this is the list to read.")
    for key, tier, seam in sorted(open_gaps):
        print(f"  {key:24} {tier:12} {seam}")
    if not open_gaps:
        print("  (none — every unreachable seam is either by design or declared "
              "dormant)")

    print(f"\ndeclared DORMANT ({len(dormant)}) — an adapter built, nothing "
          f"calling it")
    print("  Named in `capabilities.py:_NOT_WIRED`, so the wearer is told "
          "\"dormant\",\n  not a false green. Honest today; each is real work "
          "to wire.")
    for key, tier, seam in sorted(dormant):
        print(f"  {key:24} {tier:12} {seam}")

    print(f"\nNOT YET HOSTED BRAIN-SIDE ({len(not_yet)}) — real work, not a "
          f"design decision")
    print("  Each is a complete seam whose only consumer is the Orchestrator "
          "the shipped\n  Brain never builds. Nine capabilities left this "
          "shape on 2026-08-02 by being\n  re-hosted, not by being "
          "reclassified — these are the ones still waiting.")
    for key, tier, seam, why in sorted(not_yet):
        print(f"  {key:24} {tier:12} {seam}")
        print(f"  {'':24} {'':12} → {why}")

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
