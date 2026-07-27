"""test_decisions_log.py — structural checks on `decisions/`.

`decisions/` holds findings that were investigated and closed WITHOUT a code
change: refutations, accepted risks, deferred confirmations. A fixed bug has a
commit and a regression test; these have nothing else, so the directory is their
only record and it is worth a little enforcement.

Two properties matter, and neither survives on good intentions:

  * Entries stay machine-listable — front-matter present, status from the fixed
    set, ids unique and matching the filename, every entry in the README index.
  * Entries stay FALSIFIABLE. `What would overturn this` is the section that
    separates a decision log from a pile of assertions: it names the check that
    flips the verdict, so a stale entry can be caught rather than believed. An
    entry without one rots silently, which is the failure mode the directory
    exists to avoid.

Skips cleanly when the repo isn't on disk (an installed wheel has no
`decisions/`), so this never fails a packaged run.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# tests/ -> dreamlayer/ -> src/ -> host-python/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DECISIONS = _REPO_ROOT / "decisions"

VALID_STATUS = {"refuted", "accepted-risk", "confirmed-deferred", "needs-recheck"}
REQUIRED_FIELDS = ("id", "title", "status", "date", "area")
REQUIRED_SECTIONS = ("## Claim", "## Verdict", "## Evidence",
                     "## What would overturn this")

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _entries() -> list[Path]:
    if not _DECISIONS.is_dir():
        pytest.skip("decisions/ not on disk (installed package, not a checkout)")
    return sorted(p for p in _DECISIONS.glob("[0-9]*.md"))


def _front_matter(path: Path) -> dict[str, str]:
    m = _FRONT.match(path.read_text())
    assert m, f"{path.name}: no YAML front-matter block — start the file with ---"
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip().strip('"')
    return out


def test_there_is_at_least_one_entry():
    """An empty log means the practice lapsed, which is worth knowing."""
    assert _entries(), "decisions/ has no numbered entries"


@pytest.mark.parametrize("path", _entries(), ids=lambda p: p.name)
def test_entry_has_complete_front_matter(path):
    fm = _front_matter(path)
    missing = [f for f in REQUIRED_FIELDS if not fm.get(f)]
    assert not missing, f"{path.name}: front-matter missing {missing}"
    assert fm["status"] in VALID_STATUS, (
        f"{path.name}: status {fm['status']!r} is not one of {sorted(VALID_STATUS)}")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fm["date"]), (
        f"{path.name}: date {fm['date']!r} is not YYYY-MM-DD")


@pytest.mark.parametrize("path", _entries(), ids=lambda p: p.name)
def test_entry_id_matches_its_filename(path):
    fm = _front_matter(path)
    assert path.name.startswith(f"{fm['id']}-"), (
        f"{path.name}: front-matter id {fm['id']!r} does not match the filename")


@pytest.mark.parametrize("path", _entries(), ids=lambda p: p.name)
def test_entry_is_falsifiable(path):
    """The load-bearing one. Every verdict names the check that would flip it."""
    body = path.read_text()
    missing = [s for s in REQUIRED_SECTIONS if s not in body]
    assert not missing, f"{path.name}: missing section(s) {missing}"

    overturn = body.split("## What would overturn this", 1)[1]
    overturn = overturn.split("\n## ", 1)[0].strip()
    assert len(overturn) > 80, (
        f"{path.name}: 'What would overturn this' is {len(overturn)} chars — too "
        f"short to name an actual check. An entry nobody can refute is an "
        f"assertion, not a decision.")


def test_ids_are_unique():
    seen: dict[str, str] = {}
    for path in _entries():
        i = _front_matter(path)["id"]
        assert i not in seen, f"duplicate id {i}: {seen[i]} and {path.name}"
        seen[i] = path.name


def test_every_entry_is_in_the_readme_index():
    """A log you cannot skim is a log nobody reads before re-raising a finding."""
    readme = (_DECISIONS / "README.md").read_text()
    for path in _entries():
        assert path.name in readme, (
            f"{path.name} is not linked from decisions/README.md's index table")
