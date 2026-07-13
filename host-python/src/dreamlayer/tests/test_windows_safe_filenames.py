"""Repo hygiene: no tracked file may carry a Windows-illegal name.

A colon in three golden PNGs (frames named by clock time, e.g. `2:48`) once made
the whole repo un-clonable on Windows — colons are reserved there. Contributor
PR #210 fixed the files and the generator was hardened so it can't recur from
that path. This test is the durable guard: it walks every git-tracked file and
fails if any basename contains a character Windows forbids, so the class of bug
can never come back from *any* source (a new script, a hand-added file, a golden
regeneration on a permissive filesystem).

Runs from the repo root via `git ls-files`; skips cleanly outside a checkout."""
import subprocess
from pathlib import Path

import pytest

# Windows forbids these in a filename component (plus control chars, and a
# trailing dot/space). `/` is the git path separator, not a filename char, so it
# is excluded here.
ILLEGAL = set('<>:"\\|?*')
REPO_ROOT = Path(__file__).resolve().parents[4]


def _tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.SubprocessError):
        pytest.skip("git not available")
    if out.returncode:
        pytest.skip("not a git checkout")
    return [p for p in out.stdout.split("\0") if p]


def test_no_windows_illegal_tracked_filenames():
    files = _tracked_files()
    assert files, "expected some tracked files"
    bad = []
    for path in files:
        name = path.rsplit("/", 1)[-1]
        if ILLEGAL & set(name) or name[-1:] in (".", " "):
            bad.append(path)
    assert not bad, (
        "tracked files with Windows-illegal names (repo won't clone on "
        "Windows):\n  " + "\n  ".join(bad))
