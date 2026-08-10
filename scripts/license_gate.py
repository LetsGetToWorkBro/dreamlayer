#!/usr/bin/env python3
"""license_gate.py — the licence half of .github/workflows/dep-audit.yml.

A CVE gate says nothing about LICENSES. A dep that quietly resolves to a
GPL/AGPL version would obligate the proprietary app to copyleft — a risk
pip-audit can't see. This reads `pip-licenses --format=json` output and fails
the build on strong copyleft (GPL/AGPL) in the scanned surface. LGPL (weak
copyleft, dynamic linking) is allowed, matching dependency-review.yml.

**An UNDECLARED licence is now a failure too (#613).** It used to be a
`::warning::`, which is the shape of a check that returns cleanly on a
question it did not actually ask: `dependency-review-action` files a package
with no `license` field and no `License ::` classifier under "we could not
detect a license", and both gates only ever fail on a name they RECOGNISE.
A package that declares nothing was therefore indistinguishable from one that
declares MIT. The two dicts below are how a package gets out of that bucket:
by somebody writing down why, not by the tool having nothing to compare.

This lives in a file rather than a heredoc inside the workflow because a
heredoc cannot be imported, and so cannot be tested — the gate could go
vacuous and every run would still be green. `test_license_gate.py` in the
host-python suite runs the functions below directly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# TRUE build/CI tooling only (never distributed). Runtime deps like
# pluggy/packaging are intentionally NOT here — they get scanned.
IGNORE = {"pip", "pip-audit", "pip-licenses", "setuptools", "wheel",
          "ruff", "mypy", "pytest", "pytest-cov", "coverage",
          "prettytable", "wcwidth", "cyclonedx-python-lib"}

# Explicitly acknowledged copyleft (reviewed, tracked) — reported, not failed.
ACK = {"ultralytics"}

# Packages that declare NO licence and are nonetheless fine to ship. Each entry
# is a sentence somebody had to write, which is the entire point: the gate fails
# on an undeclared licence, and this is the only way past it. Add an entry when
# you have READ the project's actual licensing and can say why the empty
# metadata is sloppiness rather than a claim.
#
# Empty is the correct state for the surface this job installs (privacy + llm +
# fastapi/uvicorn), which resolved to zero undeclared licences when the gate was
# written. The dict exists so the 30th package has a sanctioned way through that
# is not "turn the check back into a warning".
UNKNOWN_LICENSE_ALLOWLIST: dict[str, str] = {}

# Packages that declare no licence and whose licensing is an OPEN QUESTION.
# Listed so the gate can name which question it is failing on — never to let one
# through. An entry here fails exactly like an unlisted package; the difference
# is that the failure says "this is a known, tracked, unsettled thing" instead
# of "something new turned up", so nobody resolves it by adding it to the
# allowlist above without learning it was already looked at.
UNKNOWN_LICENSE_UNRESOLVED: dict[str, str] = {
    "piper-phonemize": (
        "UNRESOLVED (#613): no `license` field and no `License ::` classifier "
        "on PyPI. It is the native phonemiser piper links at 1.2 and it "
        "carries espeak-ng (GPL-3.0) — upstream embedded espeak-ng and "
        "relicensed to GPL-3.0 in the same 1.3.0 release, which reads as the "
        "project concluding that shipping espeak-ng is what makes the artifact "
        "GPL. What the published WHEEL distributes is not settled. Not "
        "installed by this job today (it arrives via the `voice` extra); if "
        "the scanned surface ever widens to include it, this gate goes red "
        "until #613 answers the question."
    ),
}


def _norm(name: str) -> str:
    """Canonical form for the hand-written keys of the two dicts above, so an
    entry reads the same whether the author typed `Sloppy_Wheel` or
    `sloppy-wheel`. Deliberately NOT used for IGNORE/ACK: those are the
    workflow's own sets, matched on the lowercased name exactly as the heredoc
    this file was extracted from matched them, and widening a skip list inside
    a security gate is not a formatting change."""
    return name.strip().lower().replace("_", "-")


def is_strong_copyleft(lic: str) -> bool:
    lic = lic.lower()
    if "lgpl" in lic or "lesser general public" in lic:
        return False                       # weak copyleft — allowed
    if "with" in lic and "exception" in lic:
        return False                       # e.g. GPL WITH Classpath-exception
    # a dual license "MIT OR GPL-3.0" is usable via the permissive half
    alts = [a.strip() for a in lic.replace(" / ", " or ").split(" or ")]

    def alt_is_copyleft(a: str) -> bool:
        return ("gpl" in a or "agpl" in a or "affero" in a
                or "general public license" in a)
    return all(alt_is_copyleft(a) for a in alts if a)


def is_undeclared(lic: str) -> bool:
    """pip-licenses writes an empty string or the literal `UNKNOWN` when the
    distribution's metadata carries no licence at all."""
    lic = lic.strip()
    return not lic or lic.upper() == "UNKNOWN"


def evaluate(packages: list[dict]) -> dict[str, list]:
    """Sort a pip-licenses JSON report into the buckets the gate acts on."""
    out: dict[str, list] = {"copyleft": [], "acknowledged": [],
                            "undeclared_new": [], "undeclared_unresolved": [],
                            "undeclared_allowed": [], "stale_allowlist": []}
    seen = set()
    for pkg in packages:
        raw = pkg.get("Name", "")
        lowered = raw.lower()
        name = _norm(raw)
        lic = (pkg.get("License") or "").strip()
        if lowered in IGNORE:
            continue
        seen.add(name)
        if is_undeclared(lic):
            if name in UNKNOWN_LICENSE_UNRESOLVED:
                out["undeclared_unresolved"].append(name)
            elif name in UNKNOWN_LICENSE_ALLOWLIST:
                out["undeclared_allowed"].append(name)
            else:
                out["undeclared_new"].append(name)
            continue
        if is_strong_copyleft(lic):
            key = "acknowledged" if lowered in ACK else "copyleft"
            out[key].append((pkg.get("Name", ""), lic))
    # An annotation for a package this job no longer installs is a claim nobody
    # is checking any more. Reported, never failed: the surface legitimately
    # changes, and a stale entry is untidy rather than unsafe.
    out["stale_allowlist"] = sorted(UNKNOWN_LICENSE_ALLOWLIST.keys() - seen)
    for key in ("undeclared_new", "undeclared_unresolved", "undeclared_allowed"):
        out[key].sort()
    return out


def failed(findings: dict[str, list]) -> bool:
    return bool(findings["copyleft"] or findings["undeclared_new"]
                or findings["undeclared_unresolved"])


def report(findings: dict[str, list]) -> list[str]:
    lines = []
    if findings["acknowledged"]:
        lines.append("Acknowledged copyleft (tracked, allowed):")
        lines += [f"  {n}: {lic}" for n, lic in findings["acknowledged"]]
    if findings["undeclared_allowed"]:
        lines.append("Undeclared licence, reviewed and allowlisted:")
        lines += [f"  {n}: {UNKNOWN_LICENSE_ALLOWLIST[n]}"
                  for n in findings["undeclared_allowed"]]
    if findings["stale_allowlist"]:
        lines.append("::warning::allowlisted but not in the scanned surface — "
                     "the annotation is unchecked: "
                     + ", ".join(findings["stale_allowlist"]))
    if findings["undeclared_unresolved"]:
        lines.append("FAIL: undeclared licence, and the question is open — "
                     "settle it, do not allowlist it:")
        lines += [f"  {n}: {UNKNOWN_LICENSE_UNRESOLVED[n]}"
                  for n in findings["undeclared_unresolved"]]
    if findings["undeclared_new"]:
        lines.append("FAIL: package(s) declaring NO licence and not declared in "
                     "scripts/license_gate.py. An undeclared licence is not a "
                     "permissive one — read the project's actual licensing, "
                     "then add it to UNKNOWN_LICENSE_ALLOWLIST with the reason "
                     "(or UNKNOWN_LICENSE_UNRESOLVED if you could not settle "
                     "it):")
        lines += [f"  {n}" for n in findings["undeclared_new"]]
    if findings["copyleft"]:
        lines.append("FAIL: strong-copyleft (GPL/AGPL) licenses in the scanned "
                     "surface:")
        lines += [f"  {n}: {lic}" for n, lic in findings["copyleft"]]
    if not failed(findings):
        lines.append("License gate: no un-acknowledged strong-copyleft "
                     "(GPL/AGPL) and no undeclared licenses")
    return lines


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0]) if argv else Path("licenses.json")
    findings = evaluate(json.loads(path.read_text(encoding="utf-8")))
    for line in report(findings):
        print(line)
    return 1 if failed(findings) else 0


if __name__ == "__main__":
    sys.exit(main())
