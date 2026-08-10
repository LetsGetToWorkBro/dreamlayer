"""test_license_gate.py — an undeclared license is a finding, not a shrug.

`dep-audit.yml`'s license gate failed strong copyleft by NAME, which means it
could only ever fail on a name it recognised. A package that declares no
license at all — empty `license` field, no `License ::` classifier — went into
an "unknown" bucket that printed a `::warning::` and exited 0, so it passed for
exactly the same reason a permissive one did: the tool had nothing to compare
(#613). That is a check returning cleanly on a question it did not ask, and it
is the same failure mode as the piper relicense that went unnoticed for weeks.

The first class below is the invariant, and it is deliberately not about
`piper-phonemize`: **an undeclared license fails unless somebody has written
down why it is fine.** The rest pin the careful reasoning that was already
there (dual licenses, the Classpath exception, LGPL, the acknowledged AGPL)
so that closing the unknown hole cannot quietly widen into failing things the
gate had correctly allowed for a year.

The last class is why the logic is a script and not a heredoc: a heredoc
cannot be imported, so none of this could be asserted at all — the gate could
go vacuous and every CI run would still be green.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "license_gate.py"
WORKFLOW = ROOT / ".github" / "workflows" / "dep-audit.yml"


@pytest.fixture(scope="module")
def gate() -> types.ModuleType:
    # An assert, not a skip: the workflow runs this file by path, so its
    # absence is the gate being gone, not a test that cannot run here.
    assert SCRIPT.exists(), f"dep-audit.yml's license gate is missing: {SCRIPT}"
    spec = importlib.util.spec_from_file_location("_license_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rc(gate: types.ModuleType, packages: list[dict]) -> int:
    findings = gate.evaluate(packages)
    return 1 if gate.failed(findings) else 0


def _text(gate: types.ModuleType, packages: list[dict]) -> str:
    return "\n".join(gate.report(gate.evaluate(packages)))


class TestAnUndeclaredLicenseIsNotSilent:
    """The invariant, stated over any package rather than the reported one."""

    @pytest.mark.parametrize("license_field", ["", "   ", "UNKNOWN", "unknown"])
    def test_a_package_declaring_no_license_fails_the_gate(self, gate,
                                                           license_field):
        pkgs = [{"Name": "brand-new-thing", "License": license_field}]
        assert _rc(gate, pkgs) == 1, (
            f"undeclared license passed the gate:\n{_text(gate, pkgs)}")

    def test_an_absent_license_key_fails_the_gate(self, gate):
        assert _rc(gate, [{"Name": "brand-new-thing"}]) == 1

    def test_the_failure_names_the_package_and_says_what_to_do(self, gate):
        out = _text(gate, [{"Name": "brand-new-thing", "License": ""}])
        assert "brand-new-thing" in out
        assert "UNKNOWN_LICENSE_ALLOWLIST" in out, (
            "a gate that fails without naming the way through gets reverted")

    def test_one_undeclared_package_fails_a_surface_that_is_otherwise_clean(
            self, gate):
        assert _rc(gate, [{"Name": "attrs", "License": "MIT"},
                          {"Name": "certifi", "License": "MPL-2.0"},
                          {"Name": "brand-new-thing", "License": ""}]) == 1


class TestAReviewedUnknownHasADeclaredWayThrough:
    """Otherwise the first new unknown blocks every dependency PR and the gate
    gets turned back into a warning, which is where it started."""

    def test_an_annotated_allowlist_entry_passes(self, gate, monkeypatch):
        monkeypatch.setitem(gate.UNKNOWN_LICENSE_ALLOWLIST, "sloppy-wheel",
                            "stdlib-ish wheel, metadata never filled in")
        assert _rc(gate, [{"Name": "sloppy-wheel", "License": ""}]) == 0

    def test_the_allowlisted_package_is_reported_with_its_reason(
            self, gate, monkeypatch):
        monkeypatch.setitem(gate.UNKNOWN_LICENSE_ALLOWLIST, "sloppy-wheel",
                            "stdlib-ish wheel, metadata never filled in")
        out = _text(gate, [{"Name": "sloppy-wheel", "License": ""}])
        assert "metadata never filled in" in out, (
            "an allowlist whose reasons are never printed is a bare list")

    def test_allowlisting_does_not_excuse_a_declared_copyleft_license(
            self, gate, monkeypatch):
        monkeypatch.setitem(gate.UNKNOWN_LICENSE_ALLOWLIST, "sloppy-wheel", "x")
        assert _rc(gate, [{"Name": "sloppy-wheel",
                           "License": "GPL-3.0-or-later"}]) == 1

    def test_the_name_match_is_canonical(self, gate, monkeypatch):
        monkeypatch.setitem(gate.UNKNOWN_LICENSE_ALLOWLIST, "sloppy-wheel", "x")
        assert _rc(gate, [{"Name": "Sloppy_Wheel", "License": ""}]) == 0

    def test_an_allowlist_entry_nobody_installs_is_reported_not_failed(
            self, gate, monkeypatch):
        monkeypatch.setitem(gate.UNKNOWN_LICENSE_ALLOWLIST, "long-gone", "x")
        pkgs = [{"Name": "attrs", "License": "MIT"}]
        assert _rc(gate, pkgs) == 0
        assert "long-gone" in _text(gate, pkgs)


class TestAnOpenQuestionIsNotAnAllowlistEntry:
    """#613 exists because `piper-phonemize` declares nothing and carries
    espeak-ng. Snapshotting it into the allowlist would make the gate green on
    exactly the question it was built to ask."""

    def test_an_unresolved_package_still_fails(self, gate):
        assert _rc(gate, [{"Name": "piper-phonemize", "License": ""}]) == 1

    def test_the_failure_points_at_the_open_issue(self, gate):
        out = _text(gate, [{"Name": "piper-phonemize", "License": ""}])
        assert "#613" in out
        assert "do not allowlist it" in out

    def test_the_two_lists_never_overlap(self, gate):
        both = set(gate.UNKNOWN_LICENSE_ALLOWLIST) & set(
            gate.UNKNOWN_LICENSE_UNRESOLVED)
        assert not both, f"declared fine and unsettled at once: {sorted(both)}"


class TestEveryEntryCarriesAReason:
    """A bare name is a snapshot; a reason is a decision somebody made."""

    def test_no_entry_is_annotated_with_a_shrug(self, gate):
        entries = {**gate.UNKNOWN_LICENSE_ALLOWLIST,
                   **gate.UNKNOWN_LICENSE_UNRESOLVED}
        thin = sorted(n for n, why in entries.items() if len(why.strip()) < 20)
        assert not thin, f"entries with no real justification: {thin}"

    def test_every_key_is_already_canonical(self, gate):
        """Lookups happen on the canonical name, so `Piper_Phonemize` as a key
        matches nothing — see the next test for what that actually costs."""
        entries = {**gate.UNKNOWN_LICENSE_ALLOWLIST,
                   **gate.UNKNOWN_LICENSE_UNRESOLVED}
        assert [n for n in entries if gate._norm(n) != n] == []

    def test_a_non_canonical_key_fails_the_package_it_meant_to_allow(
            self, gate, monkeypatch):
        """What a key like `Sloppy_Wheel` costs, measured rather than assumed:
        `evaluate` gates the lookup on membership with the same canonical name
        it later indexes, so nothing raises. The package is simply never
        matched — it fails as un-allowlisted, and the entry is reported stale.
        A reviewer reads a package they annotated failing anyway, next to a
        warning about a package nobody installs."""
        monkeypatch.setitem(gate.UNKNOWN_LICENSE_ALLOWLIST, "Sloppy_Wheel",
                            "reviewed: metadata never filled in upstream")
        pkgs = [{"Name": "sloppy-wheel", "License": ""}]
        out = _text(gate, pkgs)
        assert _rc(gate, pkgs) == 1, out
        assert "::warning::" in out and "Sloppy_Wheel" in out, out

    def test_piper_phonemize_is_recorded_as_unresolved(self, gate):
        why = gate.UNKNOWN_LICENSE_UNRESOLVED["piper-phonemize"]
        assert "UNRESOLVED" in why and "#613" in why


class TestTheReasoningThatWasAlreadyThereSurvives:
    """The gate got stricter about undeclared licenses; it must not have got
    stricter about the ones it already judged correctly."""

    @pytest.mark.parametrize("lic", [
        "MIT", "Apache-2.0", "BSD-3-Clause",
        "LGPL-3.0",                              # weak copyleft — allowed
        "GNU Lesser General Public License v3",
        "GPL-2.0 WITH Classpath-exception-2.0",  # the exception is the point
        "MIT OR GPL-3.0",                        # usable via the permissive half
        "Apache-2.0 / GPL-2.0",
    ])
    def test_these_pass(self, gate, lic):
        assert _rc(gate, [{"Name": "somedep", "License": lic}]) == 0, lic

    @pytest.mark.parametrize("lic", [
        "GPL-3.0-or-later", "AGPL-3.0", "GNU General Public License v2",
        "GPL-3.0 OR AGPL-3.0",
    ])
    def test_these_fail(self, gate, lic):
        assert _rc(gate, [{"Name": "somedep", "License": lic}]) == 1, lic

    def test_the_acknowledged_agpl_dependency_is_reported_not_failed(self, gate):
        pkgs = [{"Name": "ultralytics", "License": "AGPL-3.0"}]
        assert _rc(gate, pkgs) == 0
        assert "ultralytics" in _text(gate, pkgs)

    def test_build_tooling_is_skipped_even_when_it_declares_nothing(self, gate):
        assert _rc(gate, [{"Name": "wheel", "License": ""},
                          {"Name": "pip-audit", "License": "UNKNOWN"}]) == 0


class TestTheWorkflowActuallyRunsThis:
    """A tested script the workflow does not call proves nothing about CI."""

    def test_dep_audit_invokes_the_gate_script(self):
        # the invocation, not the mere name: the script is also listed under
        # `on.push.paths` below, and a bare substring check would go on passing
        # if the step that RUNS it were deleted.
        assert "python ../scripts/license_gate.py" in WORKFLOW.read_text(
            encoding="utf-8")

    def test_a_commit_touching_only_the_gate_script_still_triggers_this(self):
        # The logic moved out of the workflow, so the trigger has to follow it:
        # without this path listed, a commit changing nothing but the gate
        # matches no entry and dependency-audit never runs on it.
        block = WORKFLOW.read_text(encoding="utf-8")
        block = block.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        assert '- "scripts/license_gate.py"' in block

    @pytest.mark.parametrize("stanza", ["push", "pull_request"])
    @pytest.mark.parametrize("path", ["scripts/license_gate.py",
                                      ".github/workflows/dep-audit.yml"])
    def test_both_triggers_list_the_gate_s_own_files(self, stanza, path):
        """Asserted per stanza, because the test above reads the whole `on:`
        block and one entry satisfies it.

        The distinction is not cosmetic: for a PR from a FORK — how this
        repository receives contributions — `push` fires on the fork and never
        here, so `pull_request` is the only trigger the change can reach. With
        the gate's own two files missing from that list, a PR editing nothing
        but the licence comparison ran no dependency-audit at all: the gate did
        not run on the change to itself.
        """
        import yaml

        on = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        on = on.get("on") or on.get(True)       # PyYAML reads bare `on:` as True
        paths = on[stanza]["paths"]
        assert path in paths, (
            f"{stanza}.paths does not list {path}, so a change to it triggers "
            f"no run — see this test's docstring for why that matters most on "
            f"the pull_request side")

    def test_the_gate_is_no_longer_an_untestable_heredoc(self):
        assert "python - <<'PY'" not in WORKFLOW.read_text(encoding="utf-8")

    def test_the_cli_exit_code_the_workflow_gates_on(self, tmp_path):
        report = tmp_path / "licenses.json"
        report.write_text(json.dumps([{"Name": "brand-new-thing",
                                       "License": ""}]))
        bad = subprocess.run([sys.executable, str(SCRIPT), str(report)],
                             capture_output=True, text=True)
        assert bad.returncode == 1, bad.stdout + bad.stderr
        report.write_text(json.dumps([{"Name": "attrs", "License": "MIT"}]))
        ok = subprocess.run([sys.executable, str(SCRIPT), str(report)],
                            capture_output=True, text=True)
        assert ok.returncode == 0, ok.stdout + ok.stderr
        assert "no undeclared licenses" in ok.stdout
