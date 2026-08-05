"""One Veil gate, two different questions, and the guard that keeps them apart.

    allow_capture()   may we KEEP what we perceive?   fails CLOSED
    allow_recall()    may we READ what we know?       always open

The Brain had TWELVE hand-written gates. `allow_capture` was byte-identical in
all of them, which is why the duplication looked like tidiness. `allow_recall`
was not: most tied it to capture, `lucid_live` did not, and both sides had
argued their case in a docstring without knowing the other existed
(decisions/0009). Several of the twelve promised in prose to "mirror" the
others — true of one predicate, false of the pair, invisible to the suite.

That is settled now: **recall is unrestricted**, because incognito is about not
KEEPING, which is `PrivacyGate`'s own reading. Under the strict alternative a
wearer lost their own memory every night, quiet hours being a nightly window.

So the arithmetic here is trivial and the structural tests are the point:

  * `TestNothingWritesWhileVeiled` — the one that makes open recall SAFE. Two
    `lens_hosts` methods were gated on `allow_recall` and did not read at all.
    Asserted by DRIVING them against a veiled Brain, not by reading source: a
    grep for write-shaped names gives false positives (`all_records` is a read,
    `append` was to a local list) and false negatives, and neither tells you
    whether anything was actually persisted.
  * `TestItCannotQuietlyBecomeTwelveAgain` — no module may hand-write the
    predicate again, and the scan that checks that must actually reach the code.
"""
from __future__ import annotations

import ast
import pathlib
import tempfile

import pytest

from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.veil import VeilGate

#: Resolved from THIS file rather than from a module's `__file__`, which is
#: `str | None` and would need silencing. The path matters more than the
#: silencing: the structural tests scan `SERVER.glob("*.py")`, so a SERVER that
#: resolves anywhere wrong makes them iterate nothing and pass vacuously — a
#: green check answering a narrower question than it appears to, which is the
#: exact shape of bug this file exists to prevent.
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


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


class TestCaptureFailsClosed:
    def test_veiled_means_no_capture(self):
        assert VeilGate(_Brain(True)).allow_capture() is False
        assert VeilGate(_Brain(False)).allow_capture() is True

    def test_an_unreadable_posture_is_treated_as_veiled(self):
        """A broken trust signal must never resolve to "record it". A gate that
        fails open on an exception is worse than no gate — it looks present."""
        assert VeilGate(_Unreadable()).allow_capture() is False


class TestRecallIsUnrestricted:
    def test_recall_survives_the_veil(self):
        """Not a fail-open and not a stub.

        `PrivacyGate.allow_recall` is blocked only by an explicit pause, and
        this Brain has no pause input — every term of `incognito_now()` is a
        capture posture. True is the honest mapping of a term that can never be
        set, which is a different thing from a hole.
        """
        assert VeilGate(_Brain(True)).allow_recall() is True
        assert VeilGate(_Brain(False)).allow_recall() is True

    def test_an_unreadable_posture_does_not_leak_into_capture(self):
        """Recall being unconditional must not soften the other answer."""
        g = VeilGate(_Unreadable())
        assert g.allow_recall() is True
        assert g.allow_capture() is False


class TestNothingWritesWhileVeiled:
    """The guard that makes open recall safe, and the reason it is behavioural.

    `resume()` and `quest_complete()` were gated on `allow_recall` while doing
    no reading at all — `resume` stamps a frame and calls `save_stasis()`,
    `quest_complete` pays XP and writes badge unlocks. While recall was closed
    that miscategorisation was invisible, because nothing could fire either
    way. Open recall and both would persist a record of what the wearer did
    DURING a veiled stretch, which is exactly what the capture gate stops.

    Both are capture-gated now. These spy on the persistence call and assert it
    never happens, rather than on a return value a mis-gated method would still
    produce.
    """

    @staticmethod
    def _veil(monkeypatch, brain, up: bool):
        """Via monkeypatch, NOT `type(brain).incognito_now = ...`.

        The direct assignment patches the `Brain` CLASS for the rest of the
        session. It cost 5 unrelated failures in `test_wire_w6_rehearsal` and
        `test_world_lens` that passed in isolation — a leak that looks like a
        regression in someone else's feature.
        """
        monkeypatch.setattr(type(brain), "incognito_now",
                            lambda self, _up=up: _up)

    def test_resume_persists_nothing_while_veiled(self, brain, monkeypatch):
        ls = brain.lenses()
        wrote = []
        ls.save_stasis = lambda *a, **k: wrote.append(1)
        self._veil(monkeypatch, brain, True)
        assert ls.resume() is None
        assert wrote == [], "a held thought was re-stamped and saved while veiled"

    def test_quest_complete_pays_nothing_while_veiled(self, brain, monkeypatch):
        ls = brain.lenses()
        paid = []

        class _Saga:
            def complete(self, subject):
                paid.append(subject)
                return None
        ls._saga = _Saga()
        self._veil(monkeypatch, brain, True)
        assert ls.quest_complete("water the plants") is None
        assert paid == [], "XP was paid and badges written while veiled"

    def test_they_still_work_with_the_veil_down(self, brain, monkeypatch):
        """The other half — a capture gate that never opens is not a gate, it
        is a broken feature, and these two tests are worth nothing apart."""
        self._veil(monkeypatch, brain, False)
        ls = brain.lenses()
        paid = []

        class _Saga:
            def complete(self, subject):
                paid.append(subject)
                return None
        ls._saga = _Saga()
        ls.quest_complete("water the plants")
        assert paid == ["water the plants"], (
            "quest_complete refuses even with the Veil down")

    def test_a_read_still_answers_while_veiled(self, brain, monkeypatch):
        """The decision itself, end to end: recall is open, so a veiled wearer
        can still ask what they already know. `trace` returns None specifically
        when refused, so anything else IS the answer."""
        self._veil(monkeypatch, brain, True)
        out = brain.lenses().trace("the lease is due Friday")
        assert out is not None, (
            "a read was refused while veiled — recall is supposed to be "
            "unrestricted (decisions/0009)")


class TestItCannotQuietlyBecomeTwelveAgain:
    def test_the_scan_actually_reaches_the_gates(self):
        """The test below is only as good as the path it walks.

        A wrong `SERVER` does not error — `glob` on a missing directory yields
        nothing, the assertion gets an empty list, and it goes green while
        checking no code at all.
        """
        assert SERVER.is_dir(), f"the gate scan points nowhere: {SERVER}"
        files = {p.name for p in SERVER.glob("*.py")}
        assert "veil.py" in files
        for expected in ("lens_hosts.py", "lucid_live.py", "ear.py",
                         "world_lens.py", "face_live.py", "dream_reactors.py"):
            assert expected in files, f"{expected} is outside the scan"
        assert len(files) > 20, f"only {len(files)} modules in scan — too few"

    def test_the_predicate_is_written_once(self):
        """No `ai_brain/server/` module may define the predicate again.

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
