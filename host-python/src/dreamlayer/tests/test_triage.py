"""test_triage.py — the noticing loop, and the guard against it going quiet.

`scripts/triage.py` reports what nobody is looking at. It is therefore the one
script in this repository whose own silence is most dangerous: a triage tool
that scans nothing prints "nothing to report", which is indistinguishable from
a healthy repository and is exactly the failure it was built to catch
(CLAUDE.md #1).

So the class that matters most here is `TestASilentScanSaysSoLoudly`. Everything
above it pins a check; that one pins the tool's honesty about itself.

The script takes every input as an argument — a path, a fetcher, a timestamp —
so all of this runs offline and deterministically. No network, no clock.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "triage.py"
WORKFLOW = ROOT / ".github" / "workflows" / "triage.yml"


@pytest.fixture(scope="module")
def triage() -> types.ModuleType:
    # An assert, not a skip: the workflow runs this file by path, so its
    # absence is the loop being gone rather than a test that cannot run here.
    assert SCRIPT.exists(), f"the triage script is missing: {SCRIPT}"
    spec = importlib.util.spec_from_file_location("_triage", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves its own module through
    # sys.modules, and without this the decorators raise on import.
    sys.modules["_triage"] = mod
    spec.loader.exec_module(mod)
    return mod


def _tree(tmp_path: pathlib.Path, **files: str) -> pathlib.Path:
    d = tmp_path / "tests"
    d.mkdir(exist_ok=True)
    for name, body in files.items():
        (d / f"{name}.py").write_text(body, encoding="utf-8")
    return d


def _project(tmp_path: pathlib.Path, workflow: str, pyproject: str):
    wf = tmp_path / "pytest.yml"
    wf.write_text(workflow, encoding="utf-8")
    pj = tmp_path / "pyproject.toml"
    pj.write_text(pyproject, encoding="utf-8")
    return wf, pj


_PYPROJECT = """
[project]
name = "x"
dependencies = ["Pillow>=10", "numpy>=1.26"]
[project.optional-dependencies]
dev = ["pytest>=8", "lupa>=2,<3"]
heavy = ["chromadb>=1,<2"]
"""

_WORKFLOW = """
      - name: Install
        run: |
          pip install -e ".[dev]"
          pip install "usearch>=2,<3" "sqlite-vec>=0.1,<1" \\
                      "wasmtime>=46,<48"
"""


class TestSkipsThatRunNowhere:
    """The memory spine and the wasm sandbox, generalised: a test gated on a
    wheel no leg installs has never executed anywhere."""

    def test_a_module_no_leg_installs_is_a_finding(self, triage, tmp_path):
        tree = _tree(tmp_path, test_a=('import pytest\n'
                                       'pytest.importorskip("nowhere_lib")\n'))
        wf, pj = _project(tmp_path, _WORKFLOW, _PYPROJECT)
        got = triage.skips_that_run_nowhere(tree, wf, pj)
        assert [f.title for f in got] == [
            "`nowhere_lib` gates tests that run in no environment"]
        assert got[0].severity == "high"

    def test_a_module_an_extra_installs_is_not_a_finding(self, triage, tmp_path):
        """`lupa` arrives through `.[dev]`, so the extras have to be expanded
        through pyproject — matching on the workflow text alone would report it
        as missing."""
        tree = _tree(tmp_path, test_a='pytest.importorskip("lupa")\n')
        wf, pj = _project(tmp_path, _WORKFLOW, _PYPROJECT)
        assert triage.skips_that_run_nowhere(tree, wf, pj) == []

    def test_a_wheel_named_after_a_line_continuation_still_counts(self, triage,
                                                                  tmp_path):
        """`wasmtime` is on the second line of a backslash-continued install.
        Read only the first line and it reads as never installed, which would
        make this tool's loudest finding a false one."""
        tree = _tree(tmp_path, test_a='pytest.importorskip("wasmtime")\n')
        wf, pj = _project(tmp_path, _WORKFLOW, _PYPROJECT)
        assert triage.skips_that_run_nowhere(tree, wf, pj) == []

    def test_a_declared_deliberate_skip_is_not_a_finding(self, triage, tmp_path,
                                                          monkeypatch):
        monkeypatch.setitem(triage.DELIBERATELY_NOT_INSTALLED, "nowhere_lib",
                            "too heavy for CI, and the fallback is covered")
        tree = _tree(tmp_path, test_a='pytest.importorskip("nowhere_lib")\n')
        wf, pj = _project(tmp_path, _WORKFLOW, _PYPROJECT)
        assert triage.skips_that_run_nowhere(tree, wf, pj) == []

    def test_the_import_name_is_mapped_to_its_distribution(self, triage,
                                                            tmp_path):
        """`import PIL` comes from `Pillow`. Without the table this reports the
        base dependency of the project as uninstalled."""
        tree = _tree(tmp_path, test_a='pytest.importorskip("PIL")\n')
        wf, pj = _project(tmp_path, _WORKFLOW, _PYPROJECT)
        assert triage.skips_that_run_nowhere(tree, wf, pj) == []

    def test_a_stale_pyc_does_not_invent_a_finding(self, triage, tmp_path):
        """A compiled test still contains the string. Reporting from one names
        a module no live test gates on, and the reader cannot tell."""
        tree = _tree(tmp_path, test_a='pass\n')
        cache = tree / "__pycache__"
        cache.mkdir()
        (cache / "test_a.cpython-311.py").write_text(
            'pytest.importorskip("ghost_lib")\n', encoding="utf-8")
        wf, pj = _project(tmp_path, _WORKFLOW, _PYPROJECT)
        assert triage.skips_that_run_nowhere(tree, wf, pj) == []


class TestEveryDeliberateSkipCarriesAReason:
    """A bare name is a snapshot; a sentence is a decision. Same rule as
    scripts/license_gate.py's allowlist."""

    def test_no_entry_is_a_shrug(self, triage):
        thin = sorted(k for k, why in triage.DELIBERATELY_NOT_INSTALLED.items()
                      if len(why.strip()) < 25)
        assert not thin, f"entries with no real justification: {thin}"

    def test_the_alias_table_has_no_guessable_rows(self, triage):
        """Every row must be a pair neither half of which derives from the
        other; a derivable one belongs in the normaliser, not the table."""
        derivable = [k for k, v in triage.IMPORT_TO_DIST.items()
                     if k.lower().replace("_", "-") == v]
        assert derivable == [], f"these need no alias row: {derivable}"


class TestGatesNobodySeesFail:
    """mutation.yml went red on 2026-07-27 and stayed red for a fortnight while
    every PR showed a full row of green."""

    def _dir(self, tmp_path, **files):
        d = tmp_path / "workflows"
        d.mkdir(exist_ok=True)
        for name, body in files.items():
            (d / f"{name}.yml").write_text(body, encoding="utf-8")
        return d

    def test_a_workflow_without_a_pull_request_trigger_is_unwatched(
            self, triage, tmp_path):
        d = self._dir(tmp_path,
                      weekly="on:\n  schedule:\n    - cron: '0 7 * * 1'\njobs:\n  x:\n",
                      gated="on:\n  pull_request:\n    paths: ['a']\njobs:\n  x:\n")
        assert triage.ungated_workflows(d) == ["weekly.yml"]

    def test_a_red_unwatched_workflow_is_a_high_finding(self, triage, tmp_path):
        d = self._dir(tmp_path,
                      weekly="on:\n  schedule:\n    - cron: '0 7 * * 1'\njobs:\n  x:\n")
        got = triage.silent_red_workflows(
            d, lambda name: {"conclusion": "failure",
                             "created_at": "2026-07-27T10:44:23Z",
                             "html_url": "http://x"})
        assert len(got) == 1 and got[0].severity == "high"
        assert "no pull request shows it" in got[0].title

    def test_a_green_one_is_not(self, triage, tmp_path):
        d = self._dir(tmp_path,
                      weekly="on:\n  schedule:\n    - cron: '0 7 * * 1'\njobs:\n  x:\n")
        assert triage.silent_red_workflows(
            d, lambda n: {"conclusion": "success"}) == []

    def test_a_pr_gated_workflow_is_never_reported_even_when_red(self, triage,
                                                                 tmp_path):
        """Its failure is already on the pull request. Repeating it here trains
        the reader to skim the report, which costs the findings that are only
        visible in it."""
        d = self._dir(tmp_path,
                      gated="on:\n  pull_request:\n    paths: ['a']\njobs:\n  x:\n")
        assert triage.silent_red_workflows(
            d, lambda n: {"conclusion": "failure"}) == []

    def test_a_workflow_that_has_never_run_is_not_a_failure(self, triage,
                                                            tmp_path):
        d = self._dir(tmp_path,
                      weekly="on:\n  schedule:\n    - cron: '0 7 * * 1'\njobs:\n  x:\n")
        assert triage.silent_red_workflows(d, lambda n: None) == []


class TestContributorsLeftWaiting:
    """#424 sat eight days on a finding about the strongest security boundary
    in the tree; #390 has a translator waiting three weeks."""

    NOW = "2026-08-10T00:00:00Z"

    def _threads(self, **kw):
        base = {"number": 424, "title": "Plugin isolation",
                "html_url": "http://x", "last_comment_author": "someone",
                "last_comment_at": "2026-08-02T00:00:00Z"}
        base.update(kw)
        return lambda: [base]

    def test_an_old_comment_from_somebody_else_is_a_finding(self, triage):
        got = triage.stale_threads(self._threads(), "owner", self.NOW)
        assert len(got) == 1 and "#424" in got[0].title
        assert "8 day(s)" in got[0].detail

    def test_the_owner_answering_last_is_not_a_finding(self, triage):
        assert triage.stale_threads(
            self._threads(last_comment_author="owner"), "owner", self.NOW) == []

    def test_a_recent_comment_is_not_yet_a_finding(self, triage):
        assert triage.stale_threads(
            self._threads(last_comment_at="2026-08-09T00:00:00Z"),
            "owner", self.NOW) == []

    def test_waiting_twice_as_long_is_escalated(self, triage):
        """Severity has to move with the wait, or a three-week-old thread reads
        the same as a five-day-old one and gets skimmed past."""
        got = triage.stale_threads(
            self._threads(last_comment_at="2026-07-19T00:00:00Z"),
            "owner", self.NOW)
        assert got[0].severity == "high"


class TestASilentScanSaysSoLoudly:
    """The class this file exists for.

    Every check above returns a list, and an empty list renders as "nothing to
    report". A scan that read no files returns the same empty list. Without
    this, the tool built to catch checks that examined nothing becomes one.
    """

    def _scan(self, triage, **examined):
        s = triage.Scan()
        s.examined = {"test_files": 400, "importorskips": 130, "workflows": 26}
        s.examined.update(examined)
        return s

    def test_a_healthy_scan_is_not_flagged(self, triage):
        assert triage.vacuous(self._scan(triage)) is None

    @pytest.mark.parametrize("field,value", [
        ("test_files", 3),        # the tree moved
        ("importorskips", 0),     # the pattern stopped matching
        ("workflows", 1),         # the directory moved
    ])
    def test_a_scan_that_read_almost_nothing_is_flagged(self, triage, field,
                                                        value):
        assert triage.vacuous(self._scan(triage, **{field: value})) is not None

    def test_the_report_leads_with_the_warning_rather_than_a_clean_bill(
            self, triage):
        out = triage.render(self._scan(triage, importorskips=0))
        assert "examined almost nothing" in out
        assert "nothing to report" not in out.lower(), (
            "a broken scan rendered as a clean repository")

    def test_a_clean_report_states_what_it_read(self, triage):
        """So "nothing to report" is always accompanied by the evidence that it
        looked. A number a reader can sanity-check beats a reassurance."""
        out = triage.render(self._scan(triage))
        assert "Nothing to report" in out
        assert "400 test files" in out and "26 workflows" in out

    def test_only_a_broken_scan_exits_non_zero(self, triage):
        """Findings must NOT fail the job. A triage report that red-blocks
        teaches people to ignore it, and the one thing it cannot survive is
        being ignored. A scan that examined nothing is different in kind — that
        is the script being broken, not the repository."""
        healthy = self._scan(triage)
        healthy.findings = [triage.Finding("k", "t", "d", "high")]
        assert triage.vacuous(healthy) is None
        assert triage.vacuous(self._scan(triage, test_files=0)) is not None


class TestTheLoopIsActuallyWired:
    """A scheduled job that never runs is the defect one layer up — and this
    whole script exists because of gates nobody sees."""

    def test_the_workflow_exists_and_runs_the_script(self):
        assert WORKFLOW.exists(), f"no triage workflow at {WORKFLOW}"
        text = WORKFLOW.read_text(encoding="utf-8")
        import re
        assert re.search(r"^\s*python\s+scripts/triage\.py", text, re.M), (
            "triage.yml does not run scripts/triage.py on a live line")

    def test_it_is_scheduled_rather_than_only_manual(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        head = text.split("\njobs:", 1)[0]
        assert "schedule:" in head, (
            "the triage loop only runs when somebody remembers to run it, "
            "which is the problem it was written to solve")

    def test_it_writes_somewhere_a_person_will_see(self):
        """Printing into a log nobody opens is the same defect wearing a
        different hat."""
        text = WORKFLOW.read_text(encoding="utf-8")
        assert "issues: write" in text, (
            "the report has to land somewhere visible; without an issue it is "
            "a log entry in a scheduled run — exactly what went unread")
