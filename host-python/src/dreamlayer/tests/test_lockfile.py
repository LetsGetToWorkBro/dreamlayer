"""uv.lock vs pyproject.toml — the lock is a claim about what you install.

Nothing here imports uv. The lock is a TOML document, so the questions that
matter can be asked of the text, and asking them in pytest is what stops the
lock rotting silently for weeks at a time (which is exactly what happened:
`birds` was declared, `birdnetlib` never made it into the lock, and the SBOM
and pip-audit workflows that read the lock went on reporting a dependency set
that no longer matched the project).

The subtle one is the last class. `[tool.uv] conflicts` is not a free
annotation — it is a promise that two extras never co-install. If somebody
later adds a conflicting extra to a shipped profile, the profile stops being
installable and nothing else in the suite notices, because every other
capability test asks "is this extra declared?", not "can it actually resolve
alongside the rest of its profile?".
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
PYPROJECT = ROOT / "pyproject.toml"
LOCK = ROOT / "uv.lock"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _lock() -> dict:
    return tomllib.loads(LOCK.read_text(encoding="utf-8"))


def _dist_name(requirement: str) -> str:
    """'mlx-lm>=0.31,<1; sys_platform==...' -> 'mlx-lm'."""
    head = re.split(r"[<>=!~;\[\s]", requirement.strip(), maxsplit=1)[0]
    return head.lower().replace("_", "-")


@pytest.fixture(scope="module")
def locked_names() -> set:
    return {p["name"].lower().replace("_", "-") for p in _lock()["package"]}


@pytest.fixture(scope="module")
def declared() -> dict:
    return _pyproject()["project"]["optional-dependencies"]


class TestTheLockDescribesTheProjectAsItIsNow:
    def test_every_declared_dependency_is_in_the_lock(self, declared,
                                                      locked_names):
        """The failure this catches is silent by construction: an extra you
        added resolves fine from PyPI at install time, so only the workflows
        reading the lock — the SBOM and the vulnerability audit — are wrong,
        and they are wrong by omission."""
        proj = _pyproject()["project"]
        groups = dict(declared, _base=proj.get("dependencies", []))
        missing = {
            group: sorted(
                n for r in reqs
                if (n := _dist_name(r)) != "dreamlayer" and n not in locked_names
            )
            for group, reqs in groups.items()
        }
        missing = {g: ns for g, ns in missing.items() if ns}
        assert not missing, (
            f"declared but absent from uv.lock — run `uv lock`: {missing}")

    def test_the_lock_offers_every_extra_the_project_declares(self, declared):
        entry = next(p for p in _lock()["package"] if p["name"] == "dreamlayer")
        provided = set(entry["metadata"]["provides-extras"])
        assert set(entry["optional-dependencies"]) <= provided
        assert set(declared) - provided == set(), (
            "uv.lock predates these extras — run `uv lock`")


class TestTheConflictTableNamesRealThings:
    def test_every_conflicting_extra_exists(self, declared):
        """A typo fails quietly in the direction that matters: uv drops a
        conflict it cannot resolve to an extra, so the pair silently stops
        being declared and the lock stops being reproducible."""
        for pair in _pyproject()["tool"]["uv"]["conflicts"]:
            for item in pair:
                assert item["extra"] in declared, item

    def test_no_shipped_profile_contains_a_conflicting_pair(self, declared):
        """The question a conflict declaration is really answering is "do
        these two ever land on the same machine?". A profile is the project's
        own statement of what lands together, so a conflict inside one is a
        profile nobody can install."""
        conflicts = {
            frozenset(i["extra"] for i in pair)
            for pair in _pyproject()["tool"]["uv"]["conflicts"]
        }
        assert declared, "no extras declared — this loop would check nothing"
        for name, entries in declared.items():
            if not name.startswith("profile-"):
                continue
            m = re.fullmatch(r"dreamlayer\[([\w,\- ]+)\]", entries[0])
            members = {e.strip() for e in m.group(1).split(",")} | {name}
            for pair in conflicts:
                assert not pair <= members, (
                    f"{name} contains the conflicting pair {sorted(pair)} — "
                    f"it cannot be installed")


# --- bounds that encode a decision, not a compatibility guess ----------------
#
# Most version bounds are housekeeping and a bot may move them freely. A few
# are the written form of a decision somebody made on purpose, and moving one
# silently un-makes it. Both entries below were added the same day this class
# was, because a bot proposed widening one of them within hours of it landing
# and every CI gate passed.
#
# That is not a bot problem, it is a coverage problem. `dependency-review`
# reads the dependency-graph DIFF, so a change to `pyproject.toml` that leaves
# `uv.lock` alone presents no new package and there is nothing for it to fail
# on — the offending version only materialises later, for whoever regenerates
# the lock next. `pip-audit` installs `[privacy,llm]` and never sees `voice` at
# all. Both gates were working; neither was being asked this question.
#
# Adding a row here is cheap. The test is not "never change this" — it is
# "changing this is a deliberate act", and editing the table alongside the pin
# is what makes it deliberate.
DECIDED_BOUNDS = [
    # (extra, distribution, bound, why)
    ("voice", "piper-tts", "<1.3",
     "piper relicensed at 1.3.0 — rhasspy/piper (MIT) became "
     "OHF-voice/piper1-gpl (GPL-3.0-or-later, it links espeak-ng). DreamLayer "
     "is Apache-2.0 and `voice` ships in profile-phone and profile-mac, so "
     "widening this puts GPL-3.0 into a shipped extra. See #609."),
    ("privacy", "cryptography", ">=50",
     "GHSA-g6cj-pr64-35w5 (a Bleichenbacher oracle in PKCS#7 EnvelopedData "
     "decryption) is fixed in 50.0.0. Lowering this reopens it, and the two "
     "advisories fixed in 49.0.0 with it. See #614."),
]


class TestABoundThatEncodesADecisionStaysPut:
    @pytest.mark.parametrize("extra,dist,bound,why", DECIDED_BOUNDS,
                             ids=[f"{e}:{d}" for e, d, _, _ in DECIDED_BOUNDS])
    def test_it_is_still_there(self, declared, extra, dist, bound, why):
        reqs = [r for r in declared[extra] if _dist_name(r) == dist]
        assert reqs, f"{dist} left the {extra!r} extra entirely — was that meant?"
        assert bound in reqs[0], (
            f"{dist} no longer carries {bound!r} in the {extra!r} extra "
            f"({reqs[0]!r}).\n\n{why}\n\n"
            f"If the decision genuinely changed, edit DECIDED_BOUNDS in this "
            f"file in the same commit. If a bot brought you here, it did not "
            f"read the comment above the pin.")


#: Lint rules enabled because each catches a DEFECT, not a style preference,
#: and each was at zero findings when it was added — so it costs no churn and
#: only ever fires on something new. Same shape as DECIDED_BOUNDS above: a
#: written-down decision, asserted, with the reason in the failure message.
#: Removing one to silence a finding should be a deliberate act.
DECIDED_LINT_RULES = [
    ("B006", "a mutable default argument, shared across every call — the shape "
             "that leaks state between tests and reads as somebody else's bug"),
    ("B012", "break/return/continue inside `finally`, which SWALLOWS the "
             "in-flight exception. This tree is full of fail-closed try/except; "
             "one of these turns a refusal into a silent success"),
    ("B018", "a bare expression statement — `x == y` where `x = y` was meant"),
    ("B019", "lru_cache on a method, pinning instances alive"),
    ("B026", "star-arg unpacking after a keyword argument"),
    ("B032", "`x: y` where `x = y` was meant — an annotation that assigns "
             "nothing and reads exactly like a statement that does"),
    ("B035", "a dict comprehension with a static key, collapsing every entry"),
]


class TestTheLintRulesThatCatchDefectsStayOn:
    @pytest.mark.parametrize("rule,why", DECIDED_LINT_RULES,
                             ids=[r for r, _ in DECIDED_LINT_RULES])
    def test_it_is_still_selected(self, rule, why):
        selected = _pyproject()["tool"]["ruff"]["lint"]["select"]
        assert rule in selected, (
            f"{rule} was dropped from [tool.ruff.lint] select.\n\n{why}\n\n"
            f"If it started firing on something legitimate, prefer a targeted "
            f"per-file-ignore over removing the rule for the whole tree — and "
            f"edit this table in the same commit either way.")

    def test_the_table_matches_what_is_actually_on(self):
        """The other direction: a rule enabled in pyproject and missing here
        is an undocumented decision, which is how the reason gets lost."""
        selected = set(_pyproject()["tool"]["ruff"]["lint"]["select"])
        bugbear = {r for r in selected if r.startswith("B")}
        assert bugbear == {r for r, _ in DECIDED_LINT_RULES}, (
            "the bugbear rules in pyproject and DECIDED_LINT_RULES disagree")


#: Modules excused from type checking (`ignore_errors = true`), each with the
#: reason it is not a one-liner. Same shape as the two tables above: a
#: written-down decision, asserted, with the reason in the failure message.
#:
#: This one is a table specifically BECAUSE the prose above it had already
#: drifted — the comment in pyproject said "Four leaf/subsystem modules" over a
#: list of five, and nothing in the suite could tell. That is the failure mode
#: this repo keeps meeting: a sentence promising something about a list, with
#: no way to know when it stops being true.
#:
#: An excused module is a hole in a gate that CI otherwise enforces over the
#: whole tree, so the cost of adding one should be a visible line in a diff and
#: a sentence saying why, not a module path appended to an array.
DECIDED_TYPE_BACKLOG = [
    ("dreamlayer.ai_brain.server.qr",
     "the QR bit-matrix is built as list[list[int|None]] and filled in place; "
     "annotating the None->int transitions carries no correctness"),
    ("dreamlayer.reality_compiler.v2.choreographer",
     "the beat->scene compiler threads several Optionals through a dynamic "
     "walk — a real typing task, not a one-liner"),
    ("dreamlayer.reality_compiler.intent_parser",
     "emits runtime-validated strings mypy cannot narrow to the Intent "
     "dataclasses' Literal fields"),
    ("dreamlayer.bridge.real_bridge",
     "its client comes from the optional brilliant-ble dependency and is None "
     "until a device connects; hardware-gated and device-free CI never runs it"),
    ("dreamlayer.reality_compiler.v2.vault_sync",
     "every value read out of a LoroDoc is loro's deep LoroValue union, so "
     "each .get(...) is a union-attr storm — CRDT plumbing, not the proof"),
]


def _excused_modules() -> set[str]:
    return {m
            for ov in _pyproject()["tool"]["mypy"].get("overrides", [])
            if ov.get("ignore_errors")
            for m in ov["module"]}


class TestTheTypeCheckingBacklogDoesNotGrowQuietly:
    @pytest.mark.parametrize("module,why", DECIDED_TYPE_BACKLOG,
                             ids=[m.rsplit(".", 1)[-1]
                                  for m, _ in DECIDED_TYPE_BACKLOG])
    def test_it_is_still_the_excused_set(self, module, why):
        assert module in _excused_modules(), (
            f"{module} came off the mypy backlog.\n\n{why}\n\n"
            f"That is good news if its types were actually written — delete "
            f"the row here in the same commit. This fails so the removal is "
            f"deliberate rather than a merge losing the override.")

    def test_nothing_was_added_without_a_reason(self):
        """The direction that matters. A module appended to `ignore_errors`
        turns the gate off for it silently — the diff is one array entry and
        every check stays green, which is how a file stops being checked
        without anybody deciding that it should.
        """
        assert _excused_modules() == {m for m, _ in DECIDED_TYPE_BACKLOG}, (
            "the mypy ignore_errors modules and DECIDED_TYPE_BACKLOG "
            "disagree — a module was excused from type checking (or excused "
            "twice) without a row saying why")

    def test_the_safety_core_is_never_excused(self):
        """The four files the audit calls the safety core, plus the Veil gate
        every capability asks. Excusing one of these is not a gradual-typing
        trade-off, and it should not be reachable by editing an array.
        """
        core = {
            "dreamlayer.ai_brain.server.veil",
            "dreamlayer.ai_brain.server.consent_gate",
            "dreamlayer.ai_brain.server.server",
            "dreamlayer.plugins.base",
        }
        excused = _excused_modules()
        assert not (core & excused), (
            f"{sorted(core & excused)} is excused from type checking — these "
            f"are the modules the Veil and the consent gate live in")


# --- the secret scanner's allowlist ------------------------------------------
GITLEAKS = ROOT.parent / ".gitleaks.toml"


def _gitleaks() -> dict:
    return tomllib.loads(GITLEAKS.read_text(encoding="utf-8"))


#: The ONLY two paths where a gitleaks finding is suppressed wholesale, with
#: what makes each defensible. A `paths` entry silences EVERY finding in a
#: matching file regardless of value, so each one is a hole the size of the
#: glob — which is why the list was cut down once already: it used to carry
#: `(^|/)tests?/`, `__tests__/`, `test_*.py` and `*.test.*`, exempting every
#: test path anywhere in the repository, so a real key committed to
#: `deploy/tests/prod.env` sailed through (refute 2026-07-18).
#:
#: That reasoning lives in a comment in .gitleaks.toml, and a comment cannot
#: tell when it stops being true. Re-widening the globs is a one-line diff that
#: turns secret scanning off for whole subtrees with every check still green.
DECIDED_SCANNER_EXEMPT_PATHS = [
    ('''^host-python/src/dreamlayer/tests/''',
     "the Python fixture tree the fake tokens were grepped from and pinned by "
     "value below"),
    ('''^phone-app/src/__tests__/''',
     "the phone-app Jest fixture tree, same audit"),
]


class TestTheSecretScannerIsNotQuietlyWidened:
    def test_the_exempt_paths_are_exactly_the_two_audited_trees(self):
        got = list(_gitleaks()["allowlist"]["paths"])
        want = [p for p, _ in DECIDED_SCANNER_EXEMPT_PATHS]
        assert got == want, (
            "the gitleaks path allowlist changed.\n\n"
            + "\n".join(f"  {p} — {why}" for p, why in DECIDED_SCANNER_EXEMPT_PATHS)
            + "\n\nA `paths` entry suppresses EVERY finding in a matching file "
              "whatever its value, so a new or broadened glob switches secret "
              "scanning off for that subtree. It was already too wide once. If "
              "something outside these trees is genuinely fixture-shaped, pin "
              "its VALUE in `regexes`/`stopwords` — those fire wherever the "
              "string appears — and edit this table only for a real decision.")

    def test_no_exemption_reaches_outside_a_test_tree(self):
        """The property the list is trying to have, asserted directly rather
        than by matching strings: an exemption that does not name a test
        directory is exempting shipped code."""
        for p in _gitleaks()["allowlist"]["paths"]:
            assert "test" in p.lower(), (
                f"{p!r} exempts a path that is not a test tree — shipped code "
                f"must be scanned")
            assert p.startswith("^"), (
                f"{p!r} is unanchored, so it matches that segment ANYWHERE in "
                f"the repository rather than at the root — which is exactly "
                f"how the previous list became a blanket hole")

    def test_the_env_example_is_still_scanned(self):
        """Called out in .gitleaks.toml as deliberately NOT exempt: it holds
        placeholders that never trip, and a real value pasted into it is
        precisely the accident that should fail."""
        for p in _gitleaks()["allowlist"]["paths"]:
            assert "env" not in p.lower(), f"{p!r} exempts .env.example"

    def test_the_allowlist_is_actually_being_read(self):
        """Without this the three above pass on a parse that found nothing:
        a renamed file or a restructured table gives empty lists, and every
        loop and comparison over them succeeds."""
        al = _gitleaks()["allowlist"]
        assert GITLEAKS.is_file(), f"no .gitleaks.toml at {GITLEAKS}"
        assert al["paths"], "the path allowlist parsed empty"
        assert len(al.get("regexes", [])) >= 8, (
            "the VALUE pins are what defend everything outside the two exempt "
            "trees; finding almost none means this file is not being read")
        assert len(al.get("stopwords", [])) >= 8
