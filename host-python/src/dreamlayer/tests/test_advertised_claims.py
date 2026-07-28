"""test_advertised_claims.py — the promises on the website, pinned to the code.

dreamlayer.app and the knowledge base make specific, checkable promises about
what this software will and will not do. Those are the claims a user relies on
when they decide to wear the thing, and they are the only claims we cannot fix
after the fact with an apology.

Every test here quotes the public sentence it defends and fails if the code
stops keeping it. A marketing claim with no test behind it is a claim that
drifts — the 2026-07-27 sweep of the site found three that already had:

  * "A retention lifecycle … hot purged after REM, warm 90 days" — the sweep
    had no live caller, so nothing ever expired. The copy was corrected, then
    the code was fixed (decisions/0001) and the copy made confident again; what
    is pinned below is now the live wiring, not its absence.
  * "no voice cloning … absent from the codebase by design" — a cloning engine
    IS present. What is actually true, and is now what we say, is narrower and
    stronger: it can only ever clone Juno's own baked clips.
  * "2,302 passing tests" — stale by roughly half.

The first two are pinned below. Deliberately NOT pinned: anything needing an
optional dependency, so this file stays green on a zero-extras install — the
promises here are about the SHIPPED default, which is the configuration a user
actually gets.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

_SRC = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# "No stranger face lookup … the shipped face embedder cannot return an
# identity at all — with no face model present it declines every frame rather
# than guessing, so there is no setting that turns stranger recognition on."
# --------------------------------------------------------------------------

pytestmark_note = "see docs privacy.html § Deliberately not built"


@pytest.mark.no_face_double
def test_the_shipped_face_embedder_cannot_identify_anyone():
    """The site's hardest promise. The PRODUCTION embedder (the autouse test
    double is opted out of here) must decline, not guess.

    A real model now EXISTS behind the opt-in `face` extra, so this asserts what
    the copy actually claims: the SHIPPED build — the default install, with no
    `face` pack and no weights — cannot return an identity. The invariant that
    keeps that true is that `face` is in no deployment profile, which is
    asserted separately and unconditionally below, because it cannot be
    satisfied by a machine simply not having installed something.

    A developer who deliberately installed the pack has not made the website
    false, so this skips there rather than failing. What must NOT happen
    silently is a BUILD shipping the pack: that is the step-3 copy change (see
    HANDOFF), and `test_the_face_pack_is_in_no_deployment_profile` is the guard
    that fires if anyone tries.
    """
    from dreamlayer.truth_lens import face_backends
    from dreamlayer.truth_lens.face_embed import FaceEmbedder

    if face_backends.available():
        pytest.skip(
            "this machine has the opt-in face pack AND its weights installed, "
            "so it is not the shipped default this claim describes. Before any "
            "BUILD ships the pack, landing/privacy.html ('cannot return an "
            "identity at all', 'keep a face database') and docs/gitbook/"
            "privacy.md ('absent from the codebase, not switched off') must "
            "change, along with the iOS purpose strings — face templates are "
            "biometric identifiers.")

    emb = FaceEmbedder()
    assert emb.available is False, (
        "the shipped FaceEmbedder reports itself available — something wired a "
        "real face model into the default build, which the site says we do not do")

    rng = np.random.default_rng(7)
    for _ in range(8):
        frame = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
        assert emb.process_frame(frame) is None, (
            "the shipped face embedder returned an embedding for an arbitrary "
            "frame — stranger recognition is reachable in the default build")


def test_the_face_pack_is_in_no_deployment_profile():
    """What actually keeps "the shipped face embedder cannot return an identity"
    true, and the one check a machine cannot accidentally satisfy by not having
    installed something.

    Every target this project ships is a `profile-*` extra. If `face` ever
    appears inside one, the default install for that target gains a face model
    and the site's sentence becomes false the moment the build goes out — so
    this is the tripwire that must fire BEFORE the copy is wrong, not after."""
    import re
    from pathlib import Path

    pyproject = (Path(__file__).resolve().parents[3] / "pyproject.toml")
    if not pyproject.exists():                    # installed wheel, not a checkout
        pytest.skip("pyproject.toml not on disk")
    text = pyproject.read_text()
    offenders = [
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if re.match(r"\s*profile-[a-z]+\s*=", line) and
        re.search(r"[\[,]\s*face\s*[,\]]", line.split("=", 1)[1])
    ]
    assert not offenders, (
        f"the `face` extra was added to deployment profile(s) {offenders} — a "
        f"default install for that target now ships a face model, so "
        f"landing/privacy.html and docs/gitbook/privacy.md are about to be "
        f"false. Change the copy in the same commit (HANDOFF step 3).")


@pytest.mark.no_face_double
def test_a_uniform_frame_does_not_assert_a_face():
    """The old stub called a 1x1 white pixel a face at 100%. Uniform and
    degenerate frames must still decline."""
    from dreamlayer.truth_lens.face_embed import FaceEmbedder

    emb = FaceEmbedder()
    for frame in (np.zeros((32, 32, 3), np.uint8),
                  np.full((32, 32, 3), 255, np.uint8),
                  np.ones((1, 1, 3), np.uint8) * 255):
        assert emb.process_frame(frame) is None


# --------------------------------------------------------------------------
# "DreamLayer never clones your voice, or anyone else's … the only reference
# clips it is ever given are her own pre-recorded takes, hard-coded in the app.
# No microphone audio … is ever used as a voice reference."
# --------------------------------------------------------------------------

def test_the_only_voice_clone_reference_is_junos_own_baked_clips():
    """Pins the shape of the single production call site. If someone ever wires
    user or bystander audio into CloneTTS, this fails — and the promise on the
    site would have to change before the code could ship."""
    server = (_SRC / "ai_brain" / "server" / "server.py").read_text()

    sites = [m for m in re.finditer(r"CloneTTS\(([^)]*)\)", server)]
    assert len(sites) == 1, (
        f"expected exactly one CloneTTS construction in server.py, found "
        f"{len(sites)}: {[s.group(0) for s in sites]}. Every additional one is a "
        f"new chance to point voice cloning at somebody's actual voice.")

    # the reference list must be built from the baked juno_*.mp3 assets, in the
    # ~10 lines above the call — not from config, a request body, or a mic buffer
    call_at = sites[0].start()
    window = server[max(0, call_at - 600):call_at]
    assert 'glob("juno_*.mp3")' in window, (
        "the CloneTTS reference clips are no longer the hard-coded juno_*.mp3 "
        "assets. The site promises no voice but Juno's is ever cloned.")


def test_no_module_feeds_captured_audio_into_the_clone_engine():
    """A blunt cross-check on the promise: nothing outside the voice-clone module
    itself and its tests may even mention CloneTTS, so there is no second path
    in that the pinned call site above would miss."""
    hits = []
    for path in _SRC.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if path.name in ("voice_clone.py",):
            continue
        if "CloneTTS" in path.read_text():
            hits.append(str(path.relative_to(_SRC)))
    assert hits == ["ai_brain/server/server.py"], (
        f"CloneTTS is referenced from unexpected modules: {hits}")


# --------------------------------------------------------------------------
# "Cloud AI is off by default and opt-in."
# --------------------------------------------------------------------------

def test_cloud_is_off_in_a_fresh_config():
    """The site says off by default, in bold, twice. A fresh install must agree."""
    from dreamlayer.ai_brain.server.store import BrainConfig

    cfg = BrainConfig()
    assert cfg.cloud_enabled is False, (
        "a fresh BrainConfig has cloud AI ON — the site says it is off by default")
    assert cfg.cloud_calls == 0
    assert not cfg.cloud_api_key, "a fresh install ships with a cloud key set"


# --------------------------------------------------------------------------
# "A retention lifecycle, and it runs … the Brain sweeps both windows when it
# starts and hourly while it is running" — docs/gitbook/perception-memory.md,
# and the privacy page's memory-lifecycle bullet.
#
# The sweep found this claim FALSE on 2026-07-27; the copy was corrected to say
# so, and this test pinned the un-wiring. It was fixed on 2026-07-28 and the
# copy is confident again, so what this pins is now the other direction: the
# claim is live, and the wiring it depends on has to stay wired.
# --------------------------------------------------------------------------

def test_the_retention_lifecycle_has_a_live_caller():
    """decisions/0001, closed. The docs say memory ages out on its own, so a
    boot must reach the sweep. Behaviour — rows actually disappearing — is
    pinned in test_brain_retention_boot.py; this is the claim-to-code link."""
    import ast
    server = (_SRC / "ai_brain" / "server" / "server.py").read_text()
    tree = ast.parse(server)
    brain = next(n for n in tree.body
                 if isinstance(n, ast.ClassDef) and n.name == "Brain")
    ctor = next(n for n in brain.body
                if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    init = ast.get_source_segment(server, ctor) or ""
    assert "self.sweep_retention()" in init, (
        "Brain.__init__ no longer sweeps retention — the docs promise memory "
        "ages out on its own, so either restore the call or correct the copy "
        "in docs/gitbook/perception-memory.md and privacy.md")

    live = (_SRC / "ai_brain" / "server" / "retention_live.py").read_text()
    assert "RetentionSweep(" in live, (
        "the Brain-side sweep no longer builds a RetentionSweep — re-check "
        "decisions/0001 before believing anything still expires")


def test_the_lifecycle_was_not_fixed_by_resurrecting_the_orchestrator():
    """The wrong fix, kept out by test. Giving `maybe_dream_tonight` a caller
    would stand a second MemoryDB and a reasoning graph up beside the Brain's
    own — what ear.py:4-10 records the team choosing twice not to do."""
    ops = (_SRC / "orchestrator" / "ops_dream_rem.py").read_text()
    assert "RetentionSweep(" in ops, "the sweep moved — re-check decisions/0001"

    callers = []
    for path in _SRC.rglob("*.py"):
        if "tests" in path.parts or path.name == "ops_dream_rem.py":
            continue
        body = path.read_text()
        if re.search(r"\.maybe_dream_tonight\s*\(", body):
            callers.append(str(path.relative_to(_SRC)))
    assert not callers, (
        f"maybe_dream_tonight now has production caller(s) {callers} — the "
        f"Orchestrator path was resurrected. The shipped Brain does not build "
        f"an Orchestrator; retention lives in ai_brain/server/retention_live.py.")
