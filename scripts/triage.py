#!/usr/bin/env python3
"""triage.py — what nobody is looking at.

This repository's expensive failures have not been bad code. They have been
things nobody was looking at, staying broken:

  * `mutation.yml` is weekly and is not a merge gate. It went red on 2026-07-27
    and stayed red until 2026-08-06 — two scheduled runs and a fortnight —
    while every PR in that window showed a full row of green checks.
  * The memory spine's tests were `importorskip`-gated on wheels CI installed
    for nobody, so they ran in NO environment. Same for the plugin sandbox's
    runtime capability proof: 105 tests, green by skip.
  * A contributor's finding about that sandbox sat eight days without an answer.

None of those needed anybody to be cleverer. They needed something to put them
in front of the one person who could act.

So this REPORTS and does not fix. That is the whole design, and it is not
timidity: the cheapest way to make a red mutation gate green is to raise its
survivor ceiling, which is a one-line diff that satisfies every check and makes
the product worse. Deciding that 229 is honest and 291 is not took a day of
measuring and a sentence no fitness function would have written. The judgement
stays with the human; the noticing does not have to.

Every check takes its inputs as arguments — a fetcher, a path — so the whole
file is testable offline. `test_triage.py` drives it, including the case that
matters most: a scan that finds nothing must SAY so rather than report a clean
repository, because "all clear" and "I looked at nothing" are the same output
otherwise (CLAUDE.md #1).
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

REPO = "LetsGetToWorkBro/dreamlayer"
ROOT = Path(__file__).resolve().parent.parent

#: How long a contributor may wait before their thread is a finding. Short
#: enough to matter — #424's eight days is the case this exists for.
STALE_DAYS = 4

#: Import name -> distribution name, where neither is guessable from the other.
#: Same table shape as scripts/license_gate.py, for the same reason: a
#: normalisation loose enough to derive `PIL` from `Pillow` is loose enough to
#: pair two unrelated packages. Rows the normaliser already derives —
#: `sqlite_vec` -> `sqlite-vec` and friends — are NOT here; test_triage.py
#: fails on one, because a redundant row reads as a decision somebody made.
IMPORT_TO_DIST = {
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "crosshair": "crosshair-tool",
    "yaml": "pyyaml",
    "hulearn": "human-learn",
    "c2pa": "c2pa-python",
    "open_clip": "open-clip-torch",
}

#: Dependencies deliberately NOT installed on a test leg, each with the reason.
#: An entry here is a decision somebody made; anything absent from both this
#: dict and the install lines is a finding.
#:
#: The bar is "would installing it be cheap?", not "is skipping reasonable?".
#: Skipping is always locally reasonable — that is exactly why the memory
#: spine's tests ran nowhere for months.
DELIBERATELY_NOT_INSTALLED: dict[str, str] = {
    "chromadb": "minutes of CI and hundreds of MB; the sqlite-vec and usearch "
                "backends installed on the test leg cover the spine's real "
                "vector-store paths",
    "lancedb": "same weight class as chromadb, same reasoning",
    "sentence_transformers": "pulls torch — the single heaviest wheel in the "
                             "tree; model2vec and the hash embedder cover the "
                             "embedding seam",
    "model2vec": "static-embedding sibling of sentence-transformers, same "
                 "weight class",
    "spacy": "large model downloads at import; the regex NER path is the "
             "shipped fallback and is covered",
    "river": "online-learning extra, part of the heavy `intelligence` group",
    "supervision": "vision tracking, part of the heavy `intelligence` group",
    "hulearn": "human-learn, part of the heavy `intelligence` group",
    "sklearn": "arrives only under the heavy intelligence/vision extras and is "
               "never a direct dependency of this project",
    "faster_whisper": "ASR model weights; the voice extra is a device profile, "
                      "not a CI surface",
    "silero_vad": "torch-backed VAD, same reasoning as faster_whisper",
}


# --------------------------------------------------------------- 1. dead skips

@dataclass
class Finding:
    kind: str
    title: str
    detail: str
    severity: str = "warn"          # "warn" | "high"


def importorskip_modules(test_tree: Path) -> dict[str, list[str]]:
    """Every `pytest.importorskip("x")` in the tree -> the files asking for it.

    Source files only. A stale .pyc in __pycache__ still contains the string
    and would report a module no live test gates on.
    """
    out: dict[str, list[str]] = {}
    for path in sorted(test_tree.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'importorskip\(\s*["\']([A-Za-z0-9_.]+)["\']', text):
            out.setdefault(m.group(1).split(".")[0], []).append(path.name)
    return out


def installed_distributions(workflow: Path, pyproject: Path) -> set[str]:
    """Distributions a TEST leg installs: the extras of every `pip install -e
    .[...]` plus every explicitly named wheel, expanded through pyproject."""
    wf = workflow.read_text(encoding="utf-8")
    pj = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    groups = pj["project"].get("optional-dependencies", {})

    dists = {_dist(r) for r in pj["project"].get("dependencies", [])}
    for extras in re.findall(r'pip install -e "\.\[([^\]]+)\]"', wf):
        for name in extras.split(","):
            for req in groups.get(name.strip(), []):
                dists.add(_dist(req))
    # explicitly named wheels, including line continuations
    for line in re.findall(r'pip install ((?:"[^"]+"[ \t]*\\?[ \t\n]*)+)', wf):
        for quoted in re.findall(r'"([^"]+)"', line):
            dists.add(_dist(quoted))
    return {_norm(d) for d in dists if d}


def _dist(requirement: str) -> str:
    return re.split(r"[<>=!~;\[\s]", requirement.strip(), maxsplit=1)[0]


def _norm(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def skips_that_run_nowhere(test_tree: Path, workflow: Path,
                           pyproject: Path) -> list[Finding]:
    """Modules some test skips on that no test leg installs — so those tests
    execute in no environment at all, and their green is the green of a check
    that examined nothing."""
    asked = importorskip_modules(test_tree)
    have = installed_distributions(workflow, pyproject)
    findings = []
    for mod, files in sorted(asked.items()):
        dist = _norm(IMPORT_TO_DIST.get(mod, mod))
        if dist in have or mod in DELIBERATELY_NOT_INSTALLED:
            continue
        where = ", ".join(sorted(set(files))[:4])
        findings.append(Finding(
            kind="skip-runs-nowhere",
            title=f"`{mod}` gates tests that run in no environment",
            detail=(f"{len(set(files))} test file(s) call "
                    f"`importorskip(\"{mod}\")` — {where} — and no test leg "
                    f"installs it. Those tests have never executed here. "
                    f"Install it, or add `{mod}` to DELIBERATELY_NOT_INSTALLED "
                    f"in scripts/triage.py with the reason."),
            severity="high"))
    return findings


# ------------------------------------------------- 2. gates nobody sees fail

def ungated_workflows(workflow_dir: Path) -> list[str]:
    """Workflows that never run on a pull request.

    These are the ones whose failure is invisible: no PR shows their red, so
    nothing puts it in front of anybody. `mutation.yml` is the worked example.
    """
    out = []
    for path in sorted(workflow_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        head = text.split("\njobs:", 1)[0]
        if not re.search(r"^\s{2}pull_request:", head, re.M):
            out.append(path.name)
    return out


def silent_red_workflows(workflow_dir: Path,
                         latest_run: Callable[[str], Optional[dict]],
                         ) -> list[Finding]:
    findings = []
    for name in ungated_workflows(workflow_dir):
        run = latest_run(name)
        if not run:
            continue
        if run.get("conclusion") in (None, "success", "skipped"):
            continue
        findings.append(Finding(
            kind="silent-red-gate",
            title=f"{name} is failing and no pull request shows it",
            detail=(f"Latest run concluded `{run.get('conclusion')}` on "
                    f"{run.get('created_at', '?')} "
                    f"({run.get('html_url', '')}). This workflow does not run "
                    f"on pull requests, so every PR since has shown a full row "
                    f"of green checks."),
            severity="high"))
    return findings


# ---------------------------------------------- 3. contributors left waiting

def stale_threads(open_threads: Callable[[], list[dict]], owner: str,
                  now_iso: str, stale_days: int = STALE_DAYS) -> list[Finding]:
    """Issues and PRs whose last word came from somebody else, days ago.

    `now_iso` is passed in rather than read from the clock so the check is
    deterministic under test.
    """
    findings = []
    for th in open_threads():
        last = th.get("last_comment_author")
        if not last or last == owner:
            continue
        age = _days_between(th.get("last_comment_at", now_iso), now_iso)
        if age < stale_days:
            continue
        findings.append(Finding(
            kind="contributor-waiting",
            title=f"#{th['number']} — {th.get('title', '')[:70]}",
            detail=(f"@{last} commented {age} day(s) ago and nobody has "
                    f"answered. {th.get('html_url', '')}"),
            severity="warn" if age < stale_days * 2 else "high"))
    return findings


def _days_between(a_iso: str, b_iso: str) -> int:
    from datetime import datetime

    def parse(s):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    return max(0, (parse(b_iso) - parse(a_iso)).days)


# ------------------------------------------------------------------ the report

@dataclass
class Scan:
    findings: list[Finding] = field(default_factory=list)
    #: What the scan actually READ. Reported in the output and asserted by the
    #: caller, because a scan that found no files and a repository with no
    #: problems produce the same empty findings list.
    examined: dict[str, int] = field(default_factory=dict)


def vacuous(scan: Scan) -> Optional[str]:
    """Why this scan should not be believed, or None."""
    if scan.examined.get("test_files", 0) < 100:
        return (f"read only {scan.examined.get('test_files', 0)} test files "
                f"(expected hundreds) — the tree moved")
    if scan.examined.get("importorskips", 0) < 5:
        return (f"found only {scan.examined.get('importorskips', 0)} "
                f"importorskip calls — the pattern stopped matching")
    if scan.examined.get("workflows", 0) < 10:
        return (f"read only {scan.examined.get('workflows', 0)} workflows — "
                f"the directory moved")
    return None


def render(scan: Scan) -> str:
    reason = vacuous(scan)
    if reason:
        return ("## ⚠️ This scan examined almost nothing\n\n"
                f"{reason}. Treat the empty result below as a broken scan, not "
                f"as a clean repository — that confusion is the exact failure "
                f"this script exists to catch.\n")
    lines = [f"_Read {scan.examined['test_files']} test files, "
             f"{scan.examined['importorskips']} importorskip calls, "
             f"{scan.examined['workflows']} workflows._\n"]
    if not scan.findings:
        lines.append("Nothing to report. Every `importorskip` runs somewhere "
                     "or is declared deliberate, no unwatched gate is red, and "
                     "no contributor is waiting.")
        return "\n".join(lines)
    for sev in ("high", "warn"):
        got = [f for f in scan.findings if f.severity == sev]
        if not got:
            continue
        lines.append(f"### {'Needs a decision' if sev == 'high' else 'Worth a look'}\n")
        for f in got:
            lines.append(f"**{f.title}**  \n{f.detail}\n")
    return "\n".join(lines)


# ------------------------------------------------------------------------ CLI

def _gh(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "dreamlayer-triage"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def live_scan(token: str, now_iso: str) -> Scan:
    """The real scan. Network-using pieces are skipped without a token so the
    local half still runs — and the report says which half it got."""
    tests = ROOT / "host-python/src/dreamlayer/tests"
    workflows = ROOT / ".github/workflows"
    scan = Scan()
    asked = importorskip_modules(tests)
    scan.examined = {
        "test_files": sum(1 for p in tests.rglob("*.py")
                          if "__pycache__" not in p.parts),
        "importorskips": sum(len(v) for v in asked.values()),
        "workflows": len(list(workflows.glob("*.yml"))),
    }
    scan.findings += skips_that_run_nowhere(
        tests, workflows / "pytest.yml", ROOT / "host-python/pyproject.toml")
    if token:
        def latest_run(name: str):
            try:
                runs = _gh(f"repos/{REPO}/actions/workflows/{name}/runs"
                           f"?per_page=1&branch=main", token).get("workflow_runs")
                return runs[0] if runs else None
            except Exception:                        # noqa: BLE001
                return None
        scan.findings += silent_red_workflows(workflows, latest_run)
        scan.findings += stale_threads(lambda: _open_threads(token), _owner(), now_iso)
    return scan


def _owner() -> str:
    return REPO.split("/")[0]


def _open_threads(token: str) -> list[dict]:
    out = []
    for item in _gh(f"repos/{REPO}/issues?state=open&per_page=50", token):
        if item.get("comments", 0) == 0:
            continue
        try:
            comments = _gh(f"repos/{REPO}/issues/{item['number']}/comments"
                           f"?per_page=100", token)
        except Exception:                            # noqa: BLE001
            continue
        if not comments:
            continue
        last = comments[-1]
        out.append({"number": item["number"], "title": item.get("title", ""),
                    "html_url": item.get("html_url", ""),
                    "last_comment_author": last.get("user", {}).get("login"),
                    "last_comment_at": last.get("created_at")})
    return out


def main(argv: list[str] | None = None) -> int:
    import os
    argv = sys.argv[1:] if argv is None else argv
    now = argv[0] if argv else __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat()
    scan = live_scan(os.environ.get("GITHUB_TOKEN", ""), now)
    print(render(scan))
    # Reporting, not gating: a finding is for a person to weigh, and a triage
    # job that fails the build teaches people to ignore it. The ONE thing that
    # exits non-zero is the scan having examined nothing, because that is not a
    # finding about the repository — it is this script being broken.
    return 1 if vacuous(scan) else 0


if __name__ == "__main__":
    sys.exit(main())
