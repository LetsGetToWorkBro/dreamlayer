"""One Veil gate — and the two tests that stop it becoming twelve again.

The Brain had TWELVE hand-written privacy gates. `allow_capture` was identical
in all of them, which is why the duplication looked like tidiness rather than
risk. `allow_recall` was not identical, and neither diverging site knew:

  * `lens_hosts` made recall the same predicate as capture, on the argument
    that reading a timeline of what was said in front of the wearer is exactly
    what the shield exists to stop. 17 call sites.
  * `lucid_live` kept recall open, on the argument that `PrivacyGate`'s own
    docstring says incognito stops KEEPING, not asking.

Several of the twelve carried a docstring claiming to "mirror" the others. By
the end that claim was false, and nothing in the suite could tell.

So the assertions that matter here are not about `VeilGate`'s arithmetic — that
part is four lines. They are:

  * there is ONE implementation (`test_the_predicate_is_written_once`), and
  * every site SAYS which posture it takes (`test_every_gate_declares_a_posture`).

Together those turn a divergence that happened by accident into one that can
only happen on purpose.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from dreamlayer.ai_brain.server.veil import (
    POSTURES, RECALL_FOLLOWS_CAPTURE, RECALL_SURVIVES_INCOGNITO, VeilGate)

#: Resolved from THIS file rather than from a module's `__file__`, which is
#: `str | None` and would need silencing. The path matters more than the
#: silencing: both structural tests below scan `SERVER.glob("*.py")`, so a
#: SERVER that resolves anywhere wrong makes them iterate nothing and pass
#: vacuously — a green check answering a narrower question than it appears to,
#: which is the exact shape of bug this file exists to prevent.
#: `test_the_scan_actually_reaches_the_gates` is the guard on that.
SERVER = pathlib.Path(__file__).resolve().parents[1] / "ai_brain" / "server"


class _Brain:
    def __init__(self, veiled):
        self._veiled = veiled

    def incognito_now(self):
        return self._veiled


class _Unreadable:
    def incognito_now(self):
        raise RuntimeError("trust store unreadable")


class TestCaptureIsTheSameEverywhere:
    """The half all twelve already agreed on. Kept exact — this is the one
    predicate a reader of any lens is entitled to assume without checking."""

    @pytest.mark.parametrize("posture", POSTURES)
    def test_veiled_means_no_capture(self, posture):
        assert VeilGate(_Brain(True), recall=posture).allow_capture() is False
        assert VeilGate(_Brain(False), recall=posture).allow_capture() is True

    @pytest.mark.parametrize("posture", POSTURES)
    def test_an_unreadable_posture_fails_closed(self, posture):
        """A broken trust signal must never resolve to "record it". This is the
        one behaviour that must not depend on the posture, because a gate that
        fails open on an exception is worse than no gate — it looks present."""
        assert VeilGate(_Unreadable(), recall=posture).allow_capture() is False


class TestRecallIsTheQuestionThatDiffered:
    def test_the_strict_posture_ties_recall_to_capture(self):
        g = VeilGate(_Brain(True), recall=RECALL_FOLLOWS_CAPTURE)
        assert g.allow_recall() is False
        assert VeilGate(_Brain(False),
                        recall=RECALL_FOLLOWS_CAPTURE).allow_recall() is True

    def test_the_surviving_posture_keeps_recall_open(self):
        """Not a fail-open. `PrivacyGate.allow_recall` is blocked only by an
        explicit pause, and this Brain has no pause input — every term of
        `incognito_now()` is about capture. True is the mapping of a term that
        can never be set, which is a different thing from a hole."""
        assert VeilGate(_Brain(True),
                        recall=RECALL_SURVIVES_INCOGNITO).allow_recall() is True

    def test_an_unreadable_posture_still_does_not_open_capture(self):
        """The surviving posture must not leak into the capture answer — that
        would turn a recall decision into a recording one."""
        g = VeilGate(_Unreadable(), recall=RECALL_SURVIVES_INCOGNITO)
        assert g.allow_recall() is True
        assert g.allow_capture() is False

    def test_the_two_postures_differ_only_while_veiled(self):
        """Unveiled they must be indistinguishable. If they ever differed with
        the Veil down, the posture would be a general behaviour switch rather
        than a statement about what the Veil covers."""
        for veiled in (False,):
            a = VeilGate(_Brain(veiled), recall=RECALL_FOLLOWS_CAPTURE)
            b = VeilGate(_Brain(veiled), recall=RECALL_SURVIVES_INCOGNITO)
            assert a.allow_recall() == b.allow_recall() is True
            assert a.allow_capture() == b.allow_capture() is True


class TestAPostureMustBeChosen:
    def test_there_is_no_default(self):
        """The original bug was not carelessness — it was two careful people
        answering locally a question nobody had written down globally. A
        default would re-create that the first time somebody adds a thirteenth
        gate without thinking about it."""
        with pytest.raises(TypeError):
            VeilGate(_Brain(False))                  # type: ignore[call-arg]

    def test_an_unknown_posture_is_refused_not_guessed(self):
        with pytest.raises(ValueError):
            VeilGate(_Brain(False), recall="whatever")

    def test_it_reports_which_one_it_took(self):
        g = VeilGate(_Brain(False), recall=RECALL_SURVIVES_INCOGNITO)
        assert g.recall_posture == RECALL_SURVIVES_INCOGNITO


class TestItCannotQuietlyBecomeTwelveAgain:
    """The two structural assertions. Everything above tests four lines of
    arithmetic; these test the thing that actually went wrong."""

    def test_the_scan_actually_reaches_the_gates(self):
        """The two tests below are only as good as the path they walk.

        A wrong `SERVER` does not error — `glob` on a missing directory yields
        nothing, both assertions get an empty list, and both go green while
        checking no code at all. So this pins that the scan sees the real
        directory, and specifically that it can see the sites the other two are
        about.
        """
        assert SERVER.is_dir(), f"the gate scan points nowhere: {SERVER}"
        files = {p.name for p in SERVER.glob("*.py")}
        assert "veil.py" in files
        # the twelve that were migrated — if the scan cannot see these, it
        # cannot see a thirteenth either
        for expected in ("lens_hosts.py", "lucid_live.py", "ear.py",
                         "world_lens.py", "face_live.py", "dream_reactors.py"):
            assert expected in files, f"{expected} is outside the scan"
        assert len(files) > 20, f"only {len(files)} modules in scan — too few"

    def test_the_predicate_is_written_once(self):
        """No `ai_brain/server/` module may define `allow_capture` again.

        Asserted over the AST rather than by grepping for a class name, because
        the twelve had twelve different names — `_LensGate`, `_EarGate`,
        `_LookGate`, `_TruthGate`, `_FaceGate`, `_VoiceGate`, `_IntroGate`,
        `_TrainGate`, two `_PostureGate`s and two `_Gate`s. What they had in
        common was the METHOD, so that is what this looks for.
        """
        offenders = []
        for path in sorted(SERVER.glob("*.py")):
            if path.name == "veil.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for m in node.body:
                        if (isinstance(m, ast.FunctionDef)
                                and m.name in ("allow_capture", "allow_recall")):
                            offenders.append(f"{path.name}:{node.name}.{m.name}")
        assert not offenders, (
            "the Veil predicate is hand-written again outside veil.py — this is "
            f"how it became twelve implementations: {offenders}")

    def test_every_gate_declares_a_posture(self):
        """A `VeilGate(...)` with no `recall=` would be a TypeError at runtime,
        so this is not about crashes — it is about the keyword being visible in
        the source a reviewer reads. A site that passes the posture through a
        variable is legal Python and defeats the point, so the literal is what
        is asserted."""
        undeclared = []
        for path in sorted(SERVER.glob("*.py")):
            if path.name == "veil.py":
                continue
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "id", "") == "VeilGate"):
                    named = {k.arg: k.value for k in node.keywords}
                    v = named.get("recall")
                    if not (isinstance(v, ast.Name) and v.id in (
                            "RECALL_FOLLOWS_CAPTURE",
                            "RECALL_SURVIVES_INCOGNITO")):
                        undeclared.append(f"{path.name}:{node.lineno}")
        assert not undeclared, (
            "a VeilGate is built without naming its recall posture in the "
            f"source — the split has to stay readable: {undeclared}")

    def test_the_split_is_still_the_documented_one(self):
        """Exactly one site takes the surviving posture, and it is Lucid
        Recall. Not a style rule: if a second lens quietly adopts it, the
        wearer's answer to "is recall veiled?" starts depending on which lens
        they asked, which is the state this module was written to end.
        """
        survivors = [
            p.name for p in sorted(SERVER.glob("*.py"))
            if p.name != "veil.py"
            and "recall=RECALL_SURVIVES_INCOGNITO" in p.read_text(encoding="utf-8")
        ]
        assert survivors == ["lucid_live.py"], (
            "the set of lenses that keep recall open while veiled changed. "
            "That is a product decision about what the Veil covers, not a "
            f"refactor — see decisions/0009: {survivors}")
